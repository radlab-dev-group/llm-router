"""
Unit tests for :class:`llm_router_lib.utils.http_async.AsyncHttpRequester` —
construction, URL building, bearer-token handling, the retry policy, the
status-code -> exception translation (shared with the sync requester),
streaming validation and client lifecycle.

No network access: the transport is replaced with ``httpx.MockTransport``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest import mock

import httpx
import pytest

from llm_router_lib.core.constants import (
    RETRY_BACKOFF_FACTOR,
    RETRY_STATUS_CODELIST,
)
from llm_router_lib.exceptions import (
    AuthenticationError,
    LLMRouterError,
    RateLimitError,
)
from llm_router_lib.utils import AsyncHttpRequester
from llm_router_lib.utils.http import raise_for_status


def _requester(
    handler: Any, **kwargs: Any
) -> AsyncHttpRequester:
    """Build an :class:`AsyncHttpRequester` on top of a mock transport."""
    return AsyncHttpRequester(
        base_url=kwargs.pop("base_url", "http://r.test"),
        token=kwargs.pop("token", ""),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


# ---------------------------------------------------------------------- #
# construction
# ---------------------------------------------------------------------- #
def test_base_url_trailing_slash_is_stripped() -> None:
    req = _requester(lambda r: httpx.Response(200))
    assert req.base_url == "http://r.test"
    req2 = _requester(
        lambda r: httpx.Response(200), base_url="http://r.test///"
    )
    assert req2.base_url == "http://r.test"


def test_timeout_and_retries_are_stored() -> None:
    req = _requester(
        lambda r: httpx.Response(200), timeout=42, retries=7
    )
    assert req.timeout == 42
    assert req.retries == 7


def test_token_sets_bearer_authorization_header() -> None:
    captured: Dict[str, Optional[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200)

    req = _requester(handler, token="sekret")

    async def run() -> None:
        await req.get("/status")

    import asyncio

    asyncio.run(run())
    assert captured["auth"] == "Bearer sekret"


def test_empty_token_does_not_set_authorization_header() -> None:
    captured: Dict[str, Optional[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200)

    req = _requester(handler, token="")

    import asyncio

    asyncio.run(req.get("/status"))
    assert captured["auth"] is None


def test_full_url_uses_single_slash() -> None:
    req = _requester(lambda r: httpx.Response(200))
    assert req._full_url("/api/ping") == "http://r.test/api/ping"
    assert req._full_url("api/ping") == "http://r.test/api/ping"


# ---------------------------------------------------------------------- #
# raise_for_status (shared status -> exception translation)
# ---------------------------------------------------------------------- #
def test_raise_for_status_passes_through_success() -> None:
    for code in (200, 201, 204, 302):
        raise_for_status(code, "")  # must not raise


def test_raise_for_status_401_raises_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        raise_for_status(401, "")


def test_raise_for_status_429_raises_rate_limit_error() -> None:
    with pytest.raises(RateLimitError):
        raise_for_status(429, "")


@pytest.mark.parametrize("status", [400, 403, 404, 500, 502, 503, 504])
def test_raise_for_status_other_errors_raise_llm_router_error(status: int) -> None:
    with pytest.raises(LLMRouterError) as ctx:
        raise_for_status(status, "boom")
    assert f"HTTP {status}" in str(ctx.value)
    assert "boom" in str(ctx.value)


# ---------------------------------------------------------------------- #
# get / post
# ---------------------------------------------------------------------- #
def _async_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def test_get_returns_validated_response() -> None:
    req = _requester(lambda r: httpx.Response(200, json={"ok": True}))
    resp = _async_run(req.get("/status"))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_post_sends_json_body() -> None:
    captured: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        assert request.method == "POST"
        return httpx.Response(200, json={"ok": True})

    req = _requester(handler)
    _async_run(req.post("/api/x", json={"a": 1}))
    assert captured == [{"a": 1}]


def test_get_404_raises_llm_router_error() -> None:
    req = _requester(lambda r: httpx.Response(404, text="nf"))
    with pytest.raises(LLMRouterError):
        _async_run(req.get("/missing"))


def test_401_raises_authentication_error() -> None:
    req = _requester(lambda r: httpx.Response(401))
    with pytest.raises(AuthenticationError):
        _async_run(req.get("/status"))


def test_429_raises_rate_limit_error_when_retries_exhausted() -> None:
    req = _requester(lambda r: httpx.Response(429), retries=0)
    with pytest.raises(RateLimitError):
        _async_run(req.get("/status"))


# ---------------------------------------------------------------------- #
# retry policy
# ---------------------------------------------------------------------- #
def test_retryable_status_then_success_is_retried_with_backoff() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="try again")
        return httpx.Response(200, json={"ok": True})

    req = _requester(handler, retries=2)
    with mock.patch.object(
        AsyncHttpRequester, "_sleep", new_callable=mock.AsyncMock
    ) as sleep_mock:
        resp = _async_run(req.get("/status"))

    assert resp.status_code == 200
    assert calls["n"] == 2
    sleep_mock.assert_awaited_once_with(RETRY_BACKOFF_FACTOR)


def test_all_retryable_statuses_exhaust_retries_and_raise() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="still down")

    req = _requester(handler, retries=2)
    with mock.patch.object(
        AsyncHttpRequester, "_sleep", new_callable=mock.AsyncMock
    ) as sleep_mock:
        with pytest.raises(LLMRouterError) as ctx:
            _async_run(req.get("/status"))

    assert calls["n"] == 3  # initial attempt + 2 retries
    assert "503" in str(ctx.value)
    # Exponential back-off: 0.5, 1.0 (no sleep before the first attempt)
    delays = [c.args[0] for c in sleep_mock.await_args_list]
    assert delays == [
        RETRY_BACKOFF_FACTOR * 1,
        RETRY_BACKOFF_FACTOR * 2,
    ]


def test_all_retry_status_codes_are_retried() -> None:
    for code in RETRY_STATUS_CODELIST:

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(code)

        req = _requester(handler, retries=0)
        with pytest.raises((RateLimitError, LLMRouterError)):
            _async_run(req.get("/status"))


def test_non_retryable_status_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    req = _requester(handler, retries=3)
    with mock.patch.object(
        AsyncHttpRequester, "_sleep", new_callable=mock.AsyncMock
    ) as sleep_mock:
        with pytest.raises(LLMRouterError):
            _async_run(req.get("/status"))

    assert calls["n"] == 1
    sleep_mock.assert_not_awaited()


def test_transport_errors_are_retried_then_succeed() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"ok": True})

    req = _requester(handler, retries=2)
    with mock.patch.object(
        AsyncHttpRequester, "_sleep", new_callable=mock.AsyncMock
    ):
        resp = _async_run(req.post("/api/x", json={}))

    assert resp.status_code == 200
    assert calls["n"] == 2


def test_transport_errors_exhaust_retries_and_raise() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("connection refused")

    req = _requester(handler, retries=2)
    with mock.patch.object(
        AsyncHttpRequester, "_sleep", new_callable=mock.AsyncMock
    ):
        with pytest.raises(LLMRouterError) as ctx:
            _async_run(req.get("/status"))

    assert calls["n"] == 3
    assert "failed after 3 attempt(s)" in str(ctx.value)


# ---------------------------------------------------------------------- #
# streaming
# ---------------------------------------------------------------------- #
def test_stream_yields_open_response_and_lines() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        async def agen():
            yield b"line1\n"
            yield b"line2\n"

        return httpx.Response(
            200,
            content=agen(),
            headers={"content-type": "text/event-stream"},
        )

    req = _requester(handler)

    async def run() -> List[str]:
        lines: List[str] = []
        async with req.stream("POST", "/api/x", json={"a": 1}) as resp:
            async for line in resp.aiter_lines():
                lines.append(line)
        return lines

    assert _async_run(run()) == ["line1", "line2"]


def test_stream_error_status_raises_and_is_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    req = _requester(handler, retries=2)

    async def run() -> None:
        async with req.stream("POST", "/api/x", json={}) as resp:
            async for _ in resp.aiter_lines():
                pass

    with pytest.raises(LLMRouterError):
        _async_run(run())
    assert calls["n"] == 1  # streaming is never retried


def test_stream_401_raises_authentication_error() -> None:
    req = _requester(lambda r: httpx.Response(401))

    async def run() -> None:
        async with req.stream("POST", "/api/x", json={}) as resp:
            async for _ in resp.aiter_lines():
                pass

    with pytest.raises(AuthenticationError):
        _async_run(run())


# ---------------------------------------------------------------------- #
# lifecycle
# ---------------------------------------------------------------------- #
def test_aclose_closes_underlying_client() -> None:
    req = _requester(lambda r: httpx.Response(200))

    async def run() -> None:
        await req.aclose()

    _async_run(run())
    assert req.client.is_closed


def test_async_context_manager_closes_client() -> None:
    req = _requester(lambda r: httpx.Response(200))

    async def run() -> None:
        async with req as entered:
            assert entered is req

    _async_run(run())
    assert req.client.is_closed
