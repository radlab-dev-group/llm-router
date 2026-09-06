"""
Unit tests for :class:`llm_router_lib.utils.http.HttpRequester` —
URL construction, bearer-token handling, the retry policy, the
status-code -> exception translation, and session lifecycle.

No network access: the underlying ``requests.Session`` methods are mocked.
"""

from __future__ import annotations

from unittest import mock

import pytest
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from llm_router_lib.core.constants import (
    RETRY_BACKOFF_FACTOR,
    RETRY_STATUS_CODELIST,
)
from llm_router_lib.exceptions import (
    AuthenticationError,
    LLMRouterError,
    RateLimitError,
)
from llm_router_lib.utils import HttpRequester


class _FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


# ---------------------------------------------------------------------- #
# construction
# ---------------------------------------------------------------------- #


def test_base_url_trailing_slash_is_stripped() -> None:
    req = HttpRequester(base_url="http://router.test/", token="")
    assert req.base_url == "http://router.test"
    req2 = HttpRequester(base_url="http://router.test///", token="")
    assert req2.base_url == "http://router.test"


def test_token_sets_bearer_authorization_header() -> None:
    req = HttpRequester(base_url="http://r.test", token="sekret")
    assert req.session.headers.get("Authorization") == "Bearer sekret"


def test_empty_token_does_not_set_authorization_header() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    assert "Authorization" not in req.session.headers


def test_timeout_and_retries_are_stored() -> None:
    req = HttpRequester(base_url="http://r.test", token="", timeout=42, retries=7)
    assert req.timeout == 42
    adapter = req.session.get_adapter("http://r.test/x")
    assert adapter.max_retries.total == 7


def test_default_logger_is_created_when_missing() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    assert req.logger is not None
    assert hasattr(req.logger, "debug")


def test_custom_logger_is_used() -> None:
    logger = mock.Mock()
    req = HttpRequester(base_url="http://r.test", token="", logger=logger)
    assert req.logger is logger


def test_retry_policy_matches_central_constants() -> None:
    req = HttpRequester(base_url="http://r.test", token="", retries=3)
    adapter = req.session.get_adapter("https://r.test/x")
    retry: Retry = adapter.max_retries  # type: ignore[assignment]
    assert isinstance(adapter, HTTPAdapter)
    assert retry.total == 3
    assert retry.backoff_factor == RETRY_BACKOFF_FACTOR
    assert set(RETRY_STATUS_CODELIST).issubset(set(retry.status_forcelist))
    allowed = {str(m).upper() for m in retry.allowed_methods}
    assert {"GET", "POST", "PUT", "DELETE"}.issubset(allowed)


# ---------------------------------------------------------------------- #
# _full_url
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/ping", "http://r.test/api/ping"),
        ("api/ping", "http://r.test/api/ping"),
        ("", "http://r.test/"),
        ("/", "http://r.test/"),
    ],
)
def test_full_url_joins_base_and_path(path: str, expected: str) -> None:
    req = HttpRequester(base_url="http://r.test/", token="")
    assert req._full_url(path) == expected


# ---------------------------------------------------------------------- #
# _handle_response (status -> exception translation)
# ---------------------------------------------------------------------- #


def test_handle_response_passes_through_success() -> None:
    resp = _FakeResponse(200, "ok")
    assert HttpRequester._handle_response(resp) is resp
    resp302 = _FakeResponse(302)
    assert HttpRequester._handle_response(resp302) is resp302


def test_handle_response_401_raises_authentication_error() -> None:
    with pytest.raises(AuthenticationError, match="token"):
        HttpRequester._handle_response(_FakeResponse(401))


def test_handle_response_429_raises_rate_limit_error() -> None:
    with pytest.raises(RateLimitError, match="Rate limit"):
        HttpRequester._handle_response(_FakeResponse(429))


@pytest.mark.parametrize("status", [400, 403, 404, 500, 502, 503, 504])
def test_handle_response_other_errors_raise_llm_router_error(status: int) -> None:
    with pytest.raises(LLMRouterError) as excinfo:
        HttpRequester._handle_response(_FakeResponse(status, "boom"))
    assert str(status) in str(excinfo.value)
    assert "boom" in str(excinfo.value)


def test_specific_errors_are_llm_router_errors() -> None:
    assert issubclass(AuthenticationError, LLMRouterError)
    assert issubclass(RateLimitError, LLMRouterError)


# ---------------------------------------------------------------------- #
# get / post (session mocked)
# ---------------------------------------------------------------------- #


def test_get_calls_session_with_full_url_and_kwargs() -> None:
    req = HttpRequester(base_url="http://r.test", token="t", timeout=9)
    req.session = mock.MagicMock()
    ok = _FakeResponse(200)
    req.session.get.return_value = ok

    resp = req.get("/api/ping", params={"a": 1})

    assert resp is ok
    req.session.get.assert_called_once_with(
        "http://r.test/api/ping", timeout=9, params={"a": 1}
    )


def test_get_without_leading_slash() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    req.session = mock.MagicMock()
    req.session.get.return_value = _FakeResponse(200)
    req.get("api/ping")
    assert req.session.get.call_args[0][0] == "http://r.test/api/ping"


def test_get_error_status_propagates_authentication_error() -> None:
    req = HttpRequester(base_url="http://r.test", token="t")
    req.session = mock.MagicMock()
    req.session.get.return_value = _FakeResponse(401)
    with pytest.raises(AuthenticationError):
        req.get("/api/x")


def test_post_sends_json_payload() -> None:
    req = HttpRequester(base_url="http://r.test", token="t", timeout=5)
    req.session = mock.MagicMock()
    ok = _FakeResponse(200)
    req.session.post.return_value = ok

    payload = {"model": "m", "texts": ["a"]}
    resp = req.post("/api/translate", json=payload, headers={"h": "1"})

    assert resp is ok
    req.session.post.assert_called_once_with(
        "http://r.test/api/translate",
        json=payload,
        timeout=5,
        headers={"h": "1"},
    )


def test_post_without_explicit_json_sends_none() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    req.session = mock.MagicMock()
    req.session.post.return_value = _FakeResponse(200)
    req.post("/api/x")
    assert req.session.post.call_args.kwargs["json"] is None


# ---------------------------------------------------------------------- #
# lifecycle
# ---------------------------------------------------------------------- #


def test_close_closes_session() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    req.session = mock.MagicMock()
    req.close()
    req.session.close.assert_called_once()


def test_context_manager_closes_session() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    req.session = mock.MagicMock()
    with req as ctx:
        assert ctx is req
    req.session.close.assert_called_once()


def test_context_manager_closes_on_exception() -> None:
    req = HttpRequester(base_url="http://r.test", token="")
    req.session = mock.MagicMock()
    with pytest.raises(RuntimeError):
        with req:
            raise RuntimeError("boom")
    req.session.close.assert_called_once()
