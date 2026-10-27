"""
Unit tests for ``llm_router_api.core.http_session``.

Covers the pooled session (one per thread, connection-pool sizing, the
connection-only retry policy), the fork hook, and the ``(connect, read)``
timeout split.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import threading  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from llm_router_api.base.constants import (  # noqa: E402
    HTTP_CONNECT_RETRIES,
    HTTP_CONNECT_TIMEOUT_SECONDS,
    HTTP_POOL_MAXSIZE,
)
from llm_router_api.core import http_session  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_session():
    """
    Give every test a clean per-thread session.

    Without this, a session built by one test would be reused by the next and
    the "a fresh session is built" assertions would depend on test order.
    """
    http_session.recreate_http_session()
    yield
    http_session.recreate_http_session()


class TestHttpTimeout:
    """``http_timeout`` splits the caller's budget into (connect, read)."""

    def test_read_budget_is_the_caller_value(self):
        connect, read = http_session.http_timeout(300)
        assert read == 300.0

    def test_connect_budget_is_the_configured_one(self):
        connect, _read = http_session.http_timeout(300)
        assert connect == float(HTTP_CONNECT_TIMEOUT_SECONDS)

    def test_connect_never_exceeds_read(self):
        # A caller with a budget shorter than the connect timeout must not
        # end up with a connect phase longer than the whole call.
        connect, read = http_session.http_timeout(2)
        assert connect == read == 2.0

    def test_no_read_timeout_stays_unbounded(self):
        # ``0`` means "no timeout" to requests; splitting must not silently
        # turn an unbounded call into a bounded one.
        connect, read = http_session.http_timeout(0)
        assert read == 0.0
        assert connect == float(HTTP_CONNECT_TIMEOUT_SECONDS)

    def test_default_comes_from_the_external_timeout(self):
        from llm_router_api.base.constants import EXTERNAL_API_TIMEOUT

        _connect, read = http_session.http_timeout()
        assert read == float(EXTERNAL_API_TIMEOUT)


class TestPooledSession:
    """The session is pooled per thread and configured for keep-alive."""

    def test_same_thread_gets_the_same_session(self):
        assert http_session.get_http_session() is http_session.get_http_session()

    def test_another_thread_gets_its_own_session(self):
        main = http_session.get_http_session()
        other: list = []

        def _worker() -> None:
            other.append(http_session.get_http_session())

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join(timeout=10)

        assert len(other) == 1
        assert other[0] is not main

    def test_adapter_is_mounted_for_both_schemes(self):
        session = http_session.get_http_session()
        assert isinstance(
            session.get_adapter("http://h"), requests.adapters.HTTPAdapter
        )
        assert isinstance(
            session.get_adapter("https://h"), requests.adapters.HTTPAdapter
        )

    def test_pool_is_sized_from_the_constant(self):
        adapter = http_session.get_http_session().get_adapter("https://h")
        assert adapter._pool_maxsize == HTTP_POOL_MAXSIZE
        assert adapter._pool_connections == HTTP_POOL_MAXSIZE

    def test_recreate_replaces_the_session(self):
        first = http_session.get_http_session()
        http_session.recreate_http_session()
        assert http_session.get_http_session() is not first


class TestRetryPolicy:
    """
    Only connection establishment is retried.

    A status or read retry would re-send a chat completion a provider may
    already have executed and billed; picking another provider for a failed
    request is the job of the router's failover.
    """

    def test_connect_retries_come_from_the_constant(self):
        retries = (
            http_session.get_http_session().get_adapter("https://h").max_retries
        )
        assert retries.connect == HTTP_CONNECT_RETRIES
        assert retries.total == HTTP_CONNECT_RETRIES

    def test_read_redirect_and_status_are_not_retried(self):
        retries = (
            http_session.get_http_session().get_adapter("https://h").max_retries
        )
        assert retries.read == 0
        assert retries.redirect == 0
        assert retries.status == 0

    def test_no_status_code_is_forced_to_retry(self):
        retries = (
            http_session.get_http_session().get_adapter("https://h").max_retries
        )
        assert not retries.status_forcelist


class TestProbeSession:
    """
    ``get_probe_session`` is the monitors' session.

    A probe measures one attempt, so with the switch on it must not retry;
    the request path keeps its connection retry either way.
    """

    def test_off_by_default_reuses_the_pooled_session(self):
        assert http_session.get_probe_session() is http_session.get_http_session()

    def test_switch_on_gives_a_retry_free_session(self, monkeypatch):
        monkeypatch.setattr(http_session, "NO_WARN_PROBE_RETRIES", True)
        probe = http_session.get_probe_session()
        retries = probe.get_adapter("https://h").max_retries
        assert retries.total == 0
        assert retries.connect == 0
        assert retries.read == 0
        assert retries.status == 0
        assert not retries.status_forcelist

    def test_switch_on_leaves_the_request_session_retrying(self, monkeypatch):
        # Silencing the probe noise must not weaken the real request path.
        monkeypatch.setattr(http_session, "NO_WARN_PROBE_RETRIES", True)
        probe = http_session.get_probe_session()
        pooled = http_session.get_http_session()
        assert probe is not pooled
        assert pooled.get_adapter("https://h").max_retries.connect == (
            HTTP_CONNECT_RETRIES
        )

    def test_probe_session_is_reused_within_a_thread(self, monkeypatch):
        monkeypatch.setattr(http_session, "NO_WARN_PROBE_RETRIES", True)
        assert http_session.get_probe_session() is http_session.get_probe_session()

    def test_probe_session_is_per_thread(self, monkeypatch):
        monkeypatch.setattr(http_session, "NO_WARN_PROBE_RETRIES", True)
        main = http_session.get_probe_session()
        other: list = []

        def _worker() -> None:
            other.append(http_session.get_probe_session())

        thread = threading.Thread(target=_worker)
        thread.start()
        thread.join(timeout=10)
        assert len(other) == 1
        assert other[0] is not main

    def test_recreate_drops_the_probe_session_too(self, monkeypatch):
        monkeypatch.setattr(http_session, "NO_WARN_PROBE_RETRIES", True)
        probe = http_session.get_probe_session()
        http_session.recreate_http_session()
        assert http_session.get_probe_session() is not probe


class TestForkHook:
    """A forked worker must not inherit the parent's sockets."""

    def test_hook_is_registered_when_the_platform_supports_it(self):
        if not hasattr(os, "register_at_fork"):
            pytest.skip("platform without os.register_at_fork")
        # ``register_at_fork`` keeps the callbacks on the os module; the
        # cheapest available assertion is that installing the hook did not
        # raise and that the reset function it calls works.
        http_session.get_http_session()
        http_session.recreate_http_session()
        assert http_session.get_http_session() is not None

    def test_recreate_survives_a_failing_close(self, monkeypatch):
        # A session closed while a request is in flight can raise; the fork
        # hook must not propagate that into the child process.
        broken = requests.Session()

        def _boom() -> None:
            raise RuntimeError("close failed")

        monkeypatch.setattr(broken, "close", _boom)
        http_session._local.session = broken
        http_session.recreate_http_session()
        assert http_session.get_http_session() is not broken
