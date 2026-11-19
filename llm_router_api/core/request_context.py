"""
Per-request context shared across the request pipeline.

The endpoint object is instantiated once at startup and shared by every
concurrent request, so any per-request value kept on ``self`` belongs to
whichever request wrote it last.  A ``ContextVar`` gives each request
(thread / greenlet) its own value, which is what the readers want.

This module is deliberately dependency-free: both
:mod:`llm_router_api.endpoints.endpoint_i` (which starts the clock) and
:mod:`llm_router_api.endpoints.http_dispatch` (which reads it to bound
failover) import it, so it must not import either of them.
"""

import contextvars
import time

from typing import Optional

# Per-request wall-clock start, in ``time.time()`` seconds.  ``None`` means
# "this context has not handled a request attempt yet" - readers must treat it
# as "unknown", never as "zero".
request_start_time: "contextvars.ContextVar[Optional[float]]" = (
    contextvars.ContextVar("llm_router_request_start_time", default=None)
)


def start_request(now: Optional[float] = None) -> float:
    """
    Mark the beginning of a request and return the timestamp that was set.

    Called once per incoming request.  A provider failover re-enters the
    endpoint pipeline, and the deadline (like ``generation_time``) has to span
    the whole request - the retries of one request are not new requests - so
    re-entering must not reset the clock.
    """
    started = time.time() if now is None else now
    request_start_time.set(started)
    return started


def elapsed_since_request_start() -> Optional[float]:
    """
    Seconds since :func:`start_request`, or ``None`` when no start is known.

    ``None`` is kept distinct from ``0.0`` on purpose: callers that enforce a
    budget must not mistake "unknown" for "just started".
    """
    start = request_start_time.get()
    if start is None:
        return None
    return time.time() - start


def request_deadline_exceeded(
    deadline_seconds: float, now: Optional[float] = None
) -> bool:
    """
    Return ``True`` when the whole-request budget of *deadline_seconds* is spent.

    Fail-open by design: an unknown start (``None``) or a non-positive
    *deadline_seconds* never blocks a retry, so the guard can only shorten a
    request that is already pathologically long, never reject a normal one.
    """
    if deadline_seconds is None or deadline_seconds <= 0:
        return False
    start = request_start_time.get()
    if start is None:
        return False
    return (time.time() if now is None else now) - start >= deadline_seconds
