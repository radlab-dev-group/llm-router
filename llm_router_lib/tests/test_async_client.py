"""
Unit tests for the :class:`llm_router_lib.async_client.AsyncLLMRouterClient`
construction, lifecycle, the meta endpoints and the unified endpoint
contract (payload handling, model fallback, error translation).

No network access: the transport is replaced with ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
import pytest

from llm_router_lib import AsyncLLMRouterClient
from llm_router_lib.core import constants as core_const
from llm_router_lib.data_models.builtin_chat import (
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
)
from llm_router_lib.data_models.builtin_utils import (
    CreateFullArticleFromTextsModel,
    GenerateArticleFromTextModel,
    GenerateArticleFromTextsModel,
    GenerateLabelModel,
    GenerateQuestionsModel,
    GenerativeAnswerModel,
    Polarity3cModel,
    SimplifyTextModel,
    TranslateModel,
)
from llm_router_lib.data_models.response import (
    ConversationResponse,
    CreateFullArticleFromTextsResponse,
    ExtendedConversationResponse,
    GenerateArticleFromTextResponse,
    GenerateArticleFromTextsResponse,
    GenerateLabelResponse,
    GenerateQuestionsResponse,
    GenerativeAnswerResponse,
    ModelsListResponse,
    PingResponse,
    Polarity3cResponse,
    SimplifyTextResponse,
    TranslateResponse,
    VersionResponse,
)
from llm_router_lib.exceptions import (
    AuthenticationError,
    LLMRouterError,
    NoArgsAndNoPayloadError,
    RateLimitError,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _json_handler(
    captured: Optional[List[Dict[str, Any]]] = None,
    status: int = 200,
    payload: Optional[dict] = None,
) -> Any:
    """Build a mock-transport handler returning *payload* (or raw text)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            body = json.loads(request.content) if request.content else None
            captured.append(
                {
                    "path": request.url.path,
                    "method": request.method,
                    "body": body,
                    "auth": request.headers.get("Authorization"),
                }
            )
        if payload is None:
            return httpx.Response(status, text="not a json body")
        return httpx.Response(status, json=payload)

    return handler


def _client(
    captured: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> AsyncLLMRouterClient:
    if "transport" not in kwargs and "payload" not in kwargs:
        kwargs["transport"] = httpx.MockTransport(_json_handler(captured))
    elif "payload" in kwargs:
        payload = kwargs.pop("payload")
        kwargs["transport"] = httpx.MockTransport(
            _json_handler(captured, payload=payload)
        )
    return AsyncLLMRouterClient(api="http://router.test", **kwargs)


# ---------------------------------------------------------------------- #
# Endpoint contract table (async parity with the sync client)
# ---------------------------------------------------------------------- #
@dataclass
class EndpointCase:
    method: str
    endpoint: str
    request_model: type
    response_cls: type
    domain_kwargs: Dict[str, Any]
    response_value: Dict[str, Any]


CASES: List[EndpointCase] = [
    EndpointCase(
        method="conversation_with_model",
        endpoint="/api/conversation_with_model",
        request_model=ConversationWithModelRequest,
        response_cls=ConversationResponse,
        domain_kwargs={"user_last_statement": "Hello!"},
        response_value={"response": "Hi there", "generation_time": 0.1},
    ),
    EndpointCase(
        method="extended_conversation_with_model",
        endpoint="/api/extended_conversation_with_model",
        request_model=ExtendedConversationWithModelRequest,
        response_cls=ExtendedConversationResponse,
        domain_kwargs={
            "user_last_statement": "Hello!",
            "system_prompt": "Be brief.",
        },
        response_value={"response": "Hi", "generation_time": 0.1},
    ),
    EndpointCase(
        method="polarity_3c",
        endpoint="/api/polarity_3c",
        request_model=Polarity3cModel,
        response_cls=Polarity3cResponse,
        domain_kwargs={"texts": ["I love this"]},
        response_value={
            "response": [{"original": "I love this", "polarity": "positive"}],
            "generation_time": 0.2,
        },
    ),
    EndpointCase(
        method="translate",
        endpoint="/api/translate",
        request_model=TranslateModel,
        response_cls=TranslateResponse,
        domain_kwargs={"texts": ["Hello"]},
        response_value={
            "response": [{"original": "Hello", "translated": "Cześć"}],
            "generation_time": 0.2,
        },
    ),
    EndpointCase(
        method="simplify_text",
        endpoint="/api/simplify_text",
        request_model=SimplifyTextModel,
        response_cls=SimplifyTextResponse,
        domain_kwargs={"texts": ["A rather long sentence"]},
        response_value={
            "response": ["A long sentence"],
            "generation_time": 0.2,
        },
    ),
    EndpointCase(
        method="generative_answer",
        endpoint="/api/generative_answer",
        request_model=GenerativeAnswerModel,
        response_cls=GenerativeAnswerResponse,
        domain_kwargs={
            "texts": ["Paris is the capital of France."],
            "question_str": "What is the capital of France?",
        },
        response_value={"response": "Paris", "generation_time": 0.3},
    ),
    EndpointCase(
        method="generate_article_from_text",
        endpoint="/api/generate_article_from_text",
        request_model=GenerateArticleFromTextModel,
        response_cls=GenerateArticleFromTextResponse,
        domain_kwargs={"text": "Source material"},
        response_value={
            "response": {"article_text": "Short article"},
            "generation_time": 0.5,
        },
    ),
    EndpointCase(
        method="generate_article_from_texts",
        endpoint="/api/generate_article_from_texts",
        request_model=GenerateArticleFromTextsModel,
        response_cls=GenerateArticleFromTextsResponse,
        domain_kwargs={"texts": ["First source", "Second source"]},
        response_value={
            "response": {"article_text": "Short article"},
            "generation_time": 0.5,
        },
    ),
    EndpointCase(
        method="create_full_article_from_texts",
        endpoint="/api/create_full_article_from_texts",
        request_model=CreateFullArticleFromTextsModel,
        response_cls=CreateFullArticleFromTextsResponse,
        domain_kwargs={
            "user_query": "Write about cats",
            "texts": ["Cats are nice."],
            "article_type": "news",
        },
        response_value={
            "response": {"article_text": "Full article"},
            "generation_time": 0.5,
        },
    ),
    EndpointCase(
        method="generate_questions",
        endpoint="/api/generate_questions",
        request_model=GenerateQuestionsModel,
        response_cls=GenerateQuestionsResponse,
        domain_kwargs={
            "texts": ["The Earth orbits the Sun."],
            "number_of_questions": 2,
        },
        response_value={
            "response": [
                {
                    "text": "The Earth orbits the Sun.",
                    "questions": ["Q1?", "Q2?"],
                }
            ],
            "generation_time": 0.4,
        },
    ),
    EndpointCase(
        method="generate_label",
        endpoint="/api/generate_label",
        request_model=GenerateLabelModel,
        response_cls=GenerateLabelResponse,
        domain_kwargs={"texts": ["Cats", "Dogs", "Hammocks"]},
        response_value={"response": "Pets", "generation_time": 0.3},
    ),
]


# ---------------------------------------------------------------------- #
# construction & lifecycle
# ---------------------------------------------------------------------- #
def test_base_url_trailing_slash_stripped() -> None:
    client = AsyncLLMRouterClient(
        api="http://r.test///",
        transport=httpx.MockTransport(lambda r: httpx.Response(200)),
    )
    assert client.base_url == "http://r.test"


def test_defaults_come_from_core_constants() -> None:
    client = _client()
    assert client.token is None
    assert client.timeout == core_const.DEFAULT_TIMEOUT_SECONDS
    assert client.retries == core_const.DEFAULT_RETRIES
    assert client.default_model is None
    assert client.stream_timeout is None
    assert client.logger is not None


def test_explicit_constructor_arguments() -> None:
    client = _client(
        token="t",
        timeout=3,
        retries=1,
        default_model="gemma",
        stream_timeout=120.0,
    )
    assert client.token == "t"
    assert client.timeout == 3
    assert client.retries == 1
    assert client.default_model == "gemma"
    assert client.stream_timeout == 120.0


def test_async_context_manager_closes_client() -> None:
    client = _client()

    async def run() -> None:
        async with client as entered:
            assert entered is client

    _run(run())
    assert client.http.client.is_closed


def test_aclose_closes_client() -> None:
    client = _client()
    _run(client.aclose())
    assert client.http.client.is_closed


# ---------------------------------------------------------------------- #
# meta endpoints
# ---------------------------------------------------------------------- #
def test_ping_returns_typed_response() -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        payload={"status": True, "body": "pong"},
    )
    resp = _run(client.ping())
    assert isinstance(resp, PingResponse)
    assert resp.status is True and resp.body == "pong"
    assert captured[0]["path"] == "/api/ping"
    assert captured[0]["method"] == "GET"


def test_version_returns_typed_response() -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(captured, payload={"version": "1.2.3"})
    resp = _run(client.version())
    assert isinstance(resp, VersionResponse)
    assert resp.version == "1.2.3"
    assert captured[0]["path"] == "/api/version"


def test_models_returns_typed_response_with_ids() -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        payload={
            "object": "list",
            "data": [{"id": "model-a"}, {"id": "model-b"}],
        },
    )
    resp = _run(client.models())
    assert isinstance(resp, ModelsListResponse)
    assert resp.ids == ["model-a", "model-b"]
    assert captured[0]["path"] == "/v1/models"


# ---------------------------------------------------------------------- #
# unified endpoint contract
# ---------------------------------------------------------------------- #
@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_payload_model_is_serialised_via_model_dump(
    case: EndpointCase,
) -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        transport=httpx.MockTransport(
            _json_handler(captured, payload=case.response_value)
        ),
    )
    request = case.request_model(model_name="test-model", **case.domain_kwargs)
    resp = _run(getattr(client, case.method)(payload=request))
    assert isinstance(resp, case.response_cls)
    assert captured[0]["path"] == case.endpoint
    assert captured[0]["method"] == "POST"
    assert captured[0]["body"] == request.model_dump()


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_named_kwargs_build_valid_payload(case: EndpointCase) -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        transport=httpx.MockTransport(
            _json_handler(captured, payload=case.response_value)
        ),
    )
    resp = _run(
        getattr(client, case.method)(**case.domain_kwargs, model="test-model")
    )
    assert isinstance(resp, case.response_cls)
    body = captured[0]["body"]
    assert body["model_name"] == "test-model"
    for key, value in case.domain_kwargs.items():
        assert body[key] == value


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_default_model_fallback(case: EndpointCase) -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        default_model="default-model",
        transport=httpx.MockTransport(
            _json_handler(captured, payload=case.response_value)
        ),
    )
    _run(getattr(client, case.method)(**case.domain_kwargs))
    assert captured[0]["body"]["model_name"] == "default-model"


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_no_args_and_no_payload_raises(case: EndpointCase) -> None:
    client = _client()
    with pytest.raises(NoArgsAndNoPayloadError):
        _run(getattr(client, case.method)())


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_no_args_with_default_model_still_raises(case: EndpointCase) -> None:
    client = _client(default_model="default-model")
    with pytest.raises(NoArgsAndNoPayloadError):
        _run(getattr(client, case.method)())


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_dict_payload_raises_type_error(case: EndpointCase) -> None:
    client = _client()
    with pytest.raises(TypeError) as ctx:
        _run(
            getattr(client, case.method)(
                payload={"model_name": "test-model", **case.domain_kwargs}
            )
        )
    assert "dict" in str(ctx.value).lower()


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_none_kwargs_fall_back_to_model_defaults(case: EndpointCase) -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        transport=httpx.MockTransport(
            _json_handler(captured, payload=case.response_value)
        ),
    )
    _run(
        getattr(client, case.method)(
            **case.domain_kwargs,
            model="test-model",
            temperature=None,
            max_new_tokens=None,
        )
    )
    body = captured[0]["body"]
    assert (
        body["temperature"] == case.request_model.model_fields["temperature"].default
    )
    assert (
        body["max_new_tokens"]
        == case.request_model.model_fields["max_new_tokens"].default
    )


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_generation_options_override_defaults(case: EndpointCase) -> None:
    captured: List[Dict[str, Any]] = []
    client = _client(
        captured,
        transport=httpx.MockTransport(
            _json_handler(captured, payload=case.response_value)
        ),
    )
    _run(
        getattr(client, case.method)(
            **case.domain_kwargs,
            model="test-model",
            temperature=0.1,
            max_new_tokens=7,
        )
    )
    body = captured[0]["body"]
    assert body["temperature"] == 0.1
    assert body["max_new_tokens"] == 7


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_401_raises_authentication_error(case: EndpointCase) -> None:
    client = _client(
        retries=0,
        transport=httpx.MockTransport(
            _json_handler(status=401, payload={"error": "bad token"})
        ),
    )
    with pytest.raises(AuthenticationError):
        _run(getattr(client, case.method)(**case.domain_kwargs, model="test-model"))


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_429_raises_rate_limit_error(case: EndpointCase) -> None:
    client = _client(
        retries=0,
        transport=httpx.MockTransport(
            _json_handler(status=429, payload={"error": "slow down"})
        ),
    )
    with pytest.raises(RateLimitError):
        _run(getattr(client, case.method)(**case.domain_kwargs, model="test-model"))


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_400_raises_llm_router_error(case: EndpointCase) -> None:
    client = _client(
        retries=0,
        transport=httpx.MockTransport(
            _json_handler(status=400, payload={"error": "bad payload"})
        ),
    )
    with pytest.raises(LLMRouterError) as ctx:
        _run(getattr(client, case.method)(**case.domain_kwargs, model="test-model"))
    assert "400" in str(ctx.value)


@pytest.mark.parametrize("case", CASES, ids=[c.method for c in CASES])
def test_invalid_json_response_raises_llm_router_error(
    case: EndpointCase,
) -> None:
    client = _client(
        transport=httpx.MockTransport(_json_handler(status=200, payload=None))
    )
    with pytest.raises(LLMRouterError):
        _run(getattr(client, case.method)(**case.domain_kwargs, model="test-model"))
