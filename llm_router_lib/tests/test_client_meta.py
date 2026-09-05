"""
Unit tests for the remaining :class:`LLMRouterClient` surface
(construction, lifecycle, and the ``ping`` / ``version`` / ``models`` meta
endpoints) plus the library-wide plumbing: the exception hierarchy, the
centralised ``core.constants`` (including the import-time environment
override) and the public package exports.

No network: service ``call_get`` methods are mocked.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from unittest import mock

import llm_router_lib
from llm_router_lib import (
    AuthenticationError,
    LLMRouterClient,
    LLMRouterError,
    RateLimitError,
    ValidationError,
)
from llm_router_lib.client import LLMRouterClient as _Client
from llm_router_lib.core import constants as core_const
from llm_router_lib.data_models.response import (
    ModelsListResponse,
    PingResponse,
    VersionResponse,
)
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_lib.services.health import ModelsService, PingService, VersionService


def _client(**kwargs) -> LLMRouterClient:
    api = kwargs.pop("api", "http://router.test")
    return LLMRouterClient(api=api, **kwargs)


# ---------------------------------------------------------------------- #
# construction
# ---------------------------------------------------------------------- #


def test_base_url_trailing_slash_stripped() -> None:
    assert _client(api="http://r.test/").base_url == "http://r.test"
    assert _client(api="http://r.test///").base_url == "http://r.test"


def test_defaults_come_from_core_constants() -> None:
    client = _client()
    assert client.token is None
    assert client.timeout == core_const.DEFAULT_TIMEOUT_SECONDS
    assert client.retries == core_const.DEFAULT_RETRIES
    assert client.default_model is None
    assert client.logger is not None


def test_explicit_timeout_retries_token_default_model() -> None:
    logger = mock.Mock()
    client = _client(
        token="t",
        timeout=3,
        retries=1,
        default_model="gemma",
        logger=logger,
    )
    assert client.token == "t"
    assert client.timeout == 3
    assert client.retries == 1
    assert client.default_model == "gemma"
    assert client.logger is logger
    # The bearer token is forwarded to the HTTP helper.
    assert client.http.session.headers.get("Authorization") == "Bearer t"


def test_no_token_means_no_authorization_header() -> None:
    client = _client()
    assert "Authorization" not in client.http.session.headers


# ---------------------------------------------------------------------- #
# lifecycle
# ---------------------------------------------------------------------- #


def test_close_closes_http_session() -> None:
    client = _client()
    client.http.session = mock.MagicMock()
    client.close()
    client.http.session.close.assert_called_once()


def test_context_manager_returns_self_and_closes() -> None:
    client = _client()
    client.http.session = mock.MagicMock()
    with client as ctx:
        assert ctx is client
    client.http.session.close.assert_called_once()


def test_context_manager_closes_on_exception() -> None:
    client = _client()
    client.http.session = mock.MagicMock()
    with pytest.raises(RuntimeError):
        with client:
            raise RuntimeError("boom")
    client.http.session.close.assert_called_once()


# ---------------------------------------------------------------------- #
# meta endpoints (service call_get mocked)
# ---------------------------------------------------------------------- #


def test_ping_returns_validated_ping_response() -> None:
    client = _client()
    with mock.patch.object(
        PingService, "call_get", return_value={"status": True, "body": "pong"}
    ) as call:
        resp = client.ping()
    call.assert_called_once()
    assert isinstance(resp, PingResponse)
    assert resp.status is True
    assert resp.body == "pong"


def test_version_returns_validated_version_response() -> None:
    client = _client()
    with mock.patch.object(
        VersionService,
        "call_get",
        return_value={"version": "1.2.3", "commit_hash": "abc"},
    ) as call:
        resp = client.version()
    call.assert_called_once()
    assert isinstance(resp, VersionResponse)
    assert resp.version == "1.2.3"


def test_models_returns_ids_and_full_entries() -> None:
    client = _client()
    with mock.patch.object(
        ModelsService,
        "call_get",
        return_value={
            "object": "list",
            "data": [
                {"id": "a"},
                {"id": "b", "type": "llm", "max_context_length": 8192},
            ],
        },
    ) as call:
        resp = client.models()
    call.assert_called_once()
    assert isinstance(resp, ModelsListResponse)
    assert resp.ids == ["a", "b"]
    assert resp.data[1].max_context_length == 8192


def test_meta_endpoint_error_propagates() -> None:
    client = _client()
    with mock.patch.object(
        PingService, "call_get", side_effect=LLMRouterError("HTTP 500: down")
    ):
        with pytest.raises(LLMRouterError, match="HTTP 500"):
            client.ping()


# ---------------------------------------------------------------------- #
# exception hierarchy
# ---------------------------------------------------------------------- #


def test_exception_hierarchy() -> None:
    assert issubclass(LLMRouterError, Exception)
    assert issubclass(AuthenticationError, LLMRouterError)
    assert issubclass(RateLimitError, LLMRouterError)
    assert issubclass(ValidationError, LLMRouterError)
    assert issubclass(NoArgsAndNoPayloadError, LLMRouterError)


def test_base_exception_catches_all_specific_errors() -> None:
    for exc_cls in (
        AuthenticationError,
        RateLimitError,
        ValidationError,
        NoArgsAndNoPayloadError,
    ):
        with pytest.raises(LLMRouterError):
            raise exc_cls("boom")


def test_package_exports() -> None:
    expected = {
        "LLMRouterClient",
        "LLMRouterError",
        "AuthenticationError",
        "RateLimitError",
        "ValidationError",
    }
    assert set(llm_router_lib.__all__) == expected
    for name in llm_router_lib.__all__:
        assert hasattr(llm_router_lib, name)
    assert llm_router_lib.LLMRouterClient is _Client


# ---------------------------------------------------------------------- #
# core constants
# ---------------------------------------------------------------------- #


def test_core_constant_values() -> None:
    assert core_const.ENV_PREFIX == "LLM_ROUTER_"
    assert core_const.DEFAULT_TIMEOUT_SECONDS == 10
    assert core_const.DEFAULT_RETRIES == 2
    assert core_const.RETRY_BACKOFF_FACTOR == 0.5
    assert core_const.RETRY_STATUS_CODELIST == [429, 500, 502, 503, 504]
    assert core_const.DEFAULT_TEMPERATURE == 0.75
    assert core_const.DEFAULT_MAX_NEW_TOKENS == 256
    assert core_const.DEFAULT_TOP_K == 50
    assert core_const.DEFAULT_TOP_P == 0.99
    assert core_const.DEFAULT_TYPICAL_P == 1.0
    assert core_const.DEFAULT_REPETITION_PENALTY == 1.2
    assert core_const.DEFAULT_KEEP_ALIVE == "30m"
    assert core_const.DEFAULT_OPTIONS == {"num_ctx": 128_000}


def test_core_package_exports() -> None:
    from llm_router_lib.core import (
        DEFAULT_KEEP_ALIVE,
        DEFAULT_OPTIONS,
        DEFAULT_RETRIES,
        DEFAULT_TIMEOUT_SECONDS,
        RETRY_BACKOFF_FACTOR,
        RETRY_STATUS_CODELIST,
    )

    assert set(llm_router_lib.core.__all__) == {
        "DEFAULT_TIMEOUT_SECONDS",
        "DEFAULT_RETRIES",
        "RETRY_BACKOFF_FACTOR",
        "RETRY_STATUS_CODELIST",
        "DEFAULT_TEMPERATURE",
        "DEFAULT_MAX_NEW_TOKENS",
        "DEFAULT_TOP_K",
        "DEFAULT_TOP_P",
        "DEFAULT_TYPICAL_P",
        "DEFAULT_REPETITION_PENALTY",
        "DEFAULT_KEEP_ALIVE",
        "DEFAULT_OPTIONS",
    }
    assert DEFAULT_KEEP_ALIVE == "30m"
    assert DEFAULT_OPTIONS == {"num_ctx": 128_000}


# DEFAULT_EP_LANGUAGE is read from the environment *at import time*, so the
# import-time behaviour is verified in a clean subprocess.
_CODE = (
    "import llm_router_lib.core.constants as c;" "print(repr(c.DEFAULT_EP_LANGUAGE))"
)


def _eval_in_clean_subprocess(env_overrides: dict) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("LLM_ROUTER_")}
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, "-c", _CODE],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_default_ep_language_defaults_to_pl_in_clean_env() -> None:
    assert _eval_in_clean_subprocess({}) == "'pl'"


def test_default_ep_language_env_override_in_clean_env() -> None:
    assert (
        _eval_in_clean_subprocess({"LLM_ROUTER_DEFAULT_EP_LANGUAGE": "en"}) == "'en'"
    )


def test_default_ep_language_value_is_stripped_in_clean_env() -> None:
    assert (
        _eval_in_clean_subprocess({"LLM_ROUTER_DEFAULT_EP_LANGUAGE": "  de  "})
        == "'de'"
    )
