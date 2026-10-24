"""
Per-thread ``requests.Session`` pool for outbound HTTP calls.

The API layer issues a large number of outbound HTTP requests (endpoint calls,
streaming responses, health and keep-alive pings).  Historically every one of
them went through the module-level ``requests.post`` / ``requests.get``
helpers, which build a brand new connection — including a full TLS handshake
for ``https`` providers — for each individual call.  Under load that
handshake dominates the added latency, and it is paid again for every
long-lived streaming response.

This module provides a :class:`requests.Session` with a keep-alive connection
pool so connections to a provider host are reused across requests.

The session is stored in a :class:`threading.local`, which keeps it correct
for both deployment shapes this project supports:

* a threaded worker (``gthread``) — every request thread owns a pool, so no
  two concurrent requests contend for the same socket;
* forked workers (the classic ``sync`` class) — a session inherited across
  ``fork`` would have its socket shared by two processes, so
  :func:`recreate_http_session` is registered as a ``fork`` hook and each
  worker rebuilds its own pool.

Retry policy
------------
Only **connection-establishment** failures are retried here.  A status- or
read-level retry would re-send a chat completion that a provider may already
have executed and billed, and re-deciding *which* provider should serve a
failed request is exactly what the router's own failover
(:mod:`llm_router_api.core.model_handler`) does — it moves on to a *different*
provider instead of hammering the one that failed.  Duplicated transport
retries would sit in front of that logic and multiply its cost without adding
reliability, so they are deliberately left to it.
"""

import os
import threading
import logging

from typing import Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from llm_router_api.base.constants import (
    EXTERNAL_API_TIMEOUT,
    HTTP_CONNECT_RETRIES,
    HTTP_CONNECT_TIMEOUT_SECONDS,
    NO_WARN_PROBE_RETRIES,
    HTTP_POOL_MAXSIZE,
)

logger = logging.getLogger(__name__)

_local = threading.local()

# Timeout accepted by ``requests``: a single number for both phases, or a
# ``(connect, read)`` pair.
Timeout = Union[float, Tuple[float, float]]


def _build_session() -> requests.Session:
    """
    Create a :class:`requests.Session` with a keep-alive connection pool.

    ``pool_connections`` bounds the number of distinct hosts kept in the pool
    and ``pool_maxsize`` the number of connections kept per host; both are set
    from :data:`~llm_router_api.base.constants.HTTP_POOL_MAXSIZE` so a worker
    talking to several providers keeps a warm socket to each of them.

    ``max_retries`` is the connection-only budget described in the module
    docstring; ``status_forcelist`` is intentionally left empty so no response
    status is ever re-sent at this layer.
    """
    session = requests.Session()
    # An explicit Retry is required: passing a plain integer to HTTPAdapter
    # means ``total``, a budget shared by *every* retry kind, so a read
    # timeout would still be re-sent.  Pinning the other counters to ``0``
    # is what actually restricts retries to connection establishment.
    retries = Retry(
        total=HTTP_CONNECT_RETRIES,
        connect=HTTP_CONNECT_RETRIES,
        read=0,
        redirect=0,
        status=0,
        status_forcelist=(),
        backoff_factor=0,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(
        pool_connections=HTTP_POOL_MAXSIZE,
        pool_maxsize=HTTP_POOL_MAXSIZE,
        max_retries=retries,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _build_probe_session() -> requests.Session:
    """
    Create a :class:`requests.Session` for health checks and keep-alive
    probes.

    Probes are measurements of a single attempt, so no retry is configured
    at all: a connection that is refused is exactly the "down" answer the
    monitor wants, and retrying it only doubles the connections and the
    urllib3 warning noise per cycle.  The request path keeps the
    connection-only retry policy of :func:`get_http_session`.
    """
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=HTTP_POOL_MAXSIZE,
        pool_maxsize=HTTP_POOL_MAXSIZE,
        max_retries=Retry(
            total=0,
            connect=0,
            read=0,
            redirect=0,
            status=0,
            status_forcelist=(),
            backoff_factor=0,
            raise_on_status=False,
        ),
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def get_probe_session() -> requests.Session:
    """
    Return the session used for health checks and keep-alive probes.

    With :data:`~llm_router_api.base.constants.NO_WARN_PROBE_RETRIES` set the
    probe uses a dedicated, retry-free session (per thread, like the request
    session); otherwise it falls back to :func:`get_http_session` so existing
    behaviour is unchanged.
    """
    if not NO_WARN_PROBE_RETRIES:
        return get_http_session()
    session = getattr(_local, "probe_session", None)
    if session is None:
        session = _build_probe_session()
        _local.probe_session = session
    return session


def get_http_session() -> requests.Session:
    """
    Return the pooled :class:`requests.Session` of the current thread.

    The session is created lazily on the first call in a thread and reused
    afterwards, so a thread that talks to the same provider repeatedly pays
    the connection cost only once.
    """
    session = getattr(_local, "session", None)
    if session is None:
        session = _build_session()
        _local.session = session
    return session


def recreate_http_session() -> None:
    """
    Drop the current thread's session so the next call builds a fresh pool.

    Installed as an ``os.register_fork`` hook so a forked worker never shares
    sockets with its parent.  Also useful in tests that need an isolated pool.
    """
    session = getattr(_local, "session", None)
    _local.session = None
    probe = getattr(_local, "probe_session", None)
    _local.probe_session = None
    if probe is not None:
        try:
            probe.close()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "HTTP probe session close during reset failed", exc_info=True
            )
    if session is not None:
        try:
            session.close()
        except Exception:  # pylint: disable=broad-exception-caught
            # Closing a session while a request is in flight can raise; a
            # failed close must not break the caller (often the fork hook).
            logger.debug("HTTP session close during reset failed", exc_info=True)


# ``register_at_fork`` exists since Python 3.7 but not on every platform
# (e.g. Windows), and a failing registration only costs the fork-safety
# optimisation, never correctness of a single-process run.
if hasattr(os, "register_at_fork"):
    try:
        os.register_at_fork(after_in_child=recreate_http_session)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Could not register the HTTP session fork hook", exc_info=True)


def http_timeout(total: Optional[float] = None) -> Timeout:
    """
    Build a ``requests`` timeout that separates connecting from reading.

    Passing a single number applies it to both phases, so a host that accepts
    the TCP connection and then never answers is only noticed after the
    *whole* budget has elapsed — a provider that is up but wedged therefore
    stalls the request instead of failing over.  Splitting the budget keeps
    the caller's read budget intact (long generations and streaming still get
    all of it) while an unreachable host is dropped after
    :data:`~llm_router_api.base.constants.HTTP_CONNECT_TIMEOUT_SECONDS`.

    Parameters
    ----------
    total : Optional[float]
        The timeout the caller would otherwise pass as a single value; it
        becomes the read budget.  Defaults to the configured external API
        timeout.

    Returns
    -------
    Timeout
        ``(connect, read)``, or the plain read budget when splitting it would
        change nothing (a connect budget of ``0`` disables it).
    """
    if total is None:
        total = EXTERNAL_API_TIMEOUT
    read = float(total)
    connect = float(HTTP_CONNECT_TIMEOUT_SECONDS)
    if connect <= 0:
        return read
    # ``0`` means "no timeout" to ``requests``; never turn it into a real
    # connect limit, or an unbounded call would silently become bounded.
    if read == 0:
        return (connect, read)
    return (min(connect, read), read)
