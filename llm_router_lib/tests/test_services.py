"""
Unit tests for the service layer: :class:`BaseConversationServiceInterface`
(call_post / call_get / JSON parsing) and the concrete endpoint bindings
(conversation, health and utility services).

The ``HttpRequester`` is replaced with a deterministic fake — no network.
"""

from __future__ import annotations

import pytest

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
from llm_router_lib.exceptions import LLMRouterError
from llm_router_lib.services.utils import GenerateLabelService
from llm_router_lib.services import (
    BaseConversationServiceInterface,
    ConversationWithModelService,
    ExtendedConversationWithModelService,
    PingService,
    VersionService,
    ModelsService,
    Polarity3cService,
    TranslateService,
    SimplifyTextService,
    GenerativeAnswerService,
    GenerateArticleFromTextService,
    CreateFullArticleFromTextsService,
    GenerateArticleFromTextsService,
    GenerateQuestionsService,
)


class _FakeResponse:
    def __init__(self, payload=None, bad_json: bool = False) -> None:
        self._payload = payload
        self._bad = bad_json
        self.url = "http://r.test/api/fake"

    def json(self):
        if self._bad:
            raise ValueError("no JSON here")
        return self._payload


class _FakeHttp:
    """Records calls and returns a canned response."""

    def __init__(self, payload=None, bad_json: bool = False) -> None:
        self.payload = payload
        self.bad_json = bad_json
        self.calls: list = []

    def _resp(self):
        return _FakeResponse(payload=self.payload, bad_json=self.bad_json)

    def post(self, endpoint, json=None, **kwargs):
        self.calls.append(("post", endpoint, json, kwargs))
        return self._resp()

    def get(self, endpoint, json=None, **kwargs):
        self.calls.append(("get", endpoint, json, kwargs))
        return self._resp()


class _FakeService(BaseConversationServiceInterface):
    endpoint = "/api/fake"
    model_cls = None


# ---------------------------------------------------------------------- #
# constructor / attribute storage
# ---------------------------------------------------------------------- #


def test_service_stores_http_and_endpoint() -> None:
    http = _FakeHttp()
    svc = _FakeService(http)
    assert svc.http is http
    assert svc.endpoint == "/api/fake"
    assert svc.model_cls is None


def test_service_accepts_custom_logger() -> None:
    logger = object()
    svc = _FakeService(_FakeHttp(), logger=logger)
    assert svc.logger is logger


def test_service_logger_defaults_to_none() -> None:
    svc = _FakeService(_FakeHttp())
    assert svc.logger is None


# ---------------------------------------------------------------------- #
# call_post / call_get
# ---------------------------------------------------------------------- #


def test_call_post_sends_payload_to_endpoint_and_parses_json() -> None:
    http = _FakeHttp(payload={"ok": 1})
    svc = _FakeService(http)
    result = svc.call_post({"a": 2})
    assert result == {"ok": 1}
    assert http.calls == [("post", "/api/fake", {"a": 2}, {})]


def test_call_get_defaults_to_no_payload() -> None:
    http = _FakeHttp(payload={"status": True})
    svc = _FakeService(http)
    assert svc.call_get() == {"status": True}
    assert http.calls == [("get", "/api/fake", None, {})]


# ---------------------------------------------------------------------- #
# JSON parsing error handling
# ---------------------------------------------------------------------- #


def test_parse_json_response_returns_dict() -> None:
    resp = _FakeResponse(payload={"a": 1})
    assert _FakeService._parse_json_response(resp) == {"a": 1}


def test_parse_json_response_invalid_json_raises_llm_router_error() -> None:
    resp = _FakeResponse(bad_json=True)
    with pytest.raises(LLMRouterError) as excinfo:
        _FakeService._parse_json_response(resp)
    assert resp.url in str(excinfo.value)
    # Original parse error is chained.
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_call_post_invalid_json_raises_llm_router_error() -> None:
    svc = _FakeService(_FakeHttp(bad_json=True))
    with pytest.raises(LLMRouterError, match="Invalid JSON response"):
        svc.call_post({"a": 1})


def test_call_get_invalid_json_raises_llm_router_error() -> None:
    svc = _FakeService(_FakeHttp(bad_json=True))
    with pytest.raises(LLMRouterError):
        svc.call_get()


# ---------------------------------------------------------------------- #
# concrete endpoint bindings
# ---------------------------------------------------------------------- #


def test_conversation_service_bindings() -> None:
    assert ConversationWithModelService.endpoint == ("/api/conversation_with_model")
    assert ConversationWithModelService.model_cls is ConversationWithModelRequest
    assert ExtendedConversationWithModelService.endpoint == (
        "/api/extended_conversation_with_model"
    )
    assert (
        ExtendedConversationWithModelService.model_cls
        is ExtendedConversationWithModelRequest
    )


def test_health_service_bindings() -> None:
    for svc, endpoint in (
        (PingService, "/api/ping"),
        (VersionService, "/api/version"),
        (ModelsService, "/v1/models"),
    ):
        assert svc.endpoint == endpoint
        assert svc.model_cls is None
        assert issubclass(svc, BaseConversationServiceInterface)


def test_utility_service_bindings() -> None:
    expected = {
        Polarity3cService: ("/api/polarity_3c", Polarity3cModel),
        TranslateService: ("/api/translate", TranslateModel),
        SimplifyTextService: ("/api/simplify_text", SimplifyTextModel),
        GenerativeAnswerService: (
            "/api/generative_answer",
            GenerativeAnswerModel,
        ),
        GenerateArticleFromTextService: (
            "/api/generate_article_from_text",
            GenerateArticleFromTextModel,
        ),
        CreateFullArticleFromTextsService: (
            "/api/create_full_article_from_texts",
            CreateFullArticleFromTextsModel,
        ),
        GenerateArticleFromTextsService: (
            "/api/generate_article_from_texts",
            GenerateArticleFromTextsModel,
        ),
        GenerateQuestionsService: (
            "/api/generate_questions",
            GenerateQuestionsModel,
        ),
        GenerateLabelService: ("/api/generate_label", GenerateLabelModel),
    }
    assert len(expected) == 9
    for svc, (endpoint, model_cls) in expected.items():
        assert svc.endpoint == endpoint, svc.__name__
        assert svc.model_cls is model_cls, svc.__name__
        assert issubclass(svc, BaseConversationServiceInterface)


def test_all_services_instantiable_with_fake_http() -> None:
    http = _FakeHttp(payload={})
    from llm_router_lib import services as svc_pkg

    for name in svc_pkg.__all__:
        cls = getattr(svc_pkg, name)
        if cls is BaseConversationServiceInterface:
            continue  # abstract
        instance = cls(http)
        assert instance.endpoint
