"""
Unit tests for the response-side Pydantic models in
``llm_router_lib.data_models.response``.

The client validates every raw service dict against one of these models and
returns the typed instance.  These tests pin down the tolerant contract:
sensible defaults, ignored extra keys, nested item models and the
convenience ``ids`` accessor.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_router_lib.data_models.response import (
    BaseResponse,
    GenerationResponse,
    PingResponse,
    VersionResponse,
    ModelInfo,
    ModelsListResponse,
    ConversationResponse,
    ExtendedConversationResponse,
    Polarity3cItem,
    Polarity3cResponse,
    TranslateItem,
    TranslateResponse,
    SimplifyTextResponse,
    TextQuestions,
    GenerateQuestionsResponse,
    GenerativeAnswerResponse,
    GenerateLabelResponse,
    ArticleText,
    GenerateArticleFromTextResponse,
    CreateFullArticleFromTextsResponse,
    GenerateArticleFromTextsResponse,
)


# ---------------------------------------------------------------------- #
# tolerant base behaviour
# ---------------------------------------------------------------------- #


def test_base_response_ignores_unknown_keys() -> None:
    resp = BaseResponse.model_validate({"unexpected": 1, "other": [1, 2]})
    assert resp.model_dump() == {}


def test_generation_response_generation_time_defaults_none() -> None:
    assert GenerationResponse().generation_time is None
    assert GenerationResponse(generation_time=1.5).generation_time == 1.5


# ---------------------------------------------------------------------- #
# health / meta
# ---------------------------------------------------------------------- #


def test_ping_response_defaults_and_parse() -> None:
    assert PingResponse().status is True
    assert PingResponse().body is None
    resp = PingResponse.model_validate({"status": True, "body": "pong"})
    assert resp.status is True
    assert resp.body == "pong"


def test_version_response_defaults_and_parse() -> None:
    assert VersionResponse().version == ""
    assert VersionResponse.model_validate({"version": "1.2.3"}).version == "1.2.3"


def test_model_info_requires_id() -> None:
    with pytest.raises(ValidationError):
        ModelInfo()
    info = ModelInfo(id="m")
    assert info.object is None
    assert info.created is None
    assert info.owned_by is None
    # LM-Studio superset fields
    assert info.max_context_length is None


def test_model_info_accepts_full_payload() -> None:
    info = ModelInfo.model_validate(
        {
            "id": "m",
            "object": "model",
            "created": 123.0,
            "owned_by": "org",
            "type": "llm",
            "publisher": "p",
            "arch": "qwen",
            "compatibility_type": "openai",
            "quantization": "q8",
            "state": "ready",
            "max_context_length": 4096,
        }
    )
    assert info.max_context_length == 4096
    assert info.owned_by == "org"


def test_models_list_response_defaults_and_ids() -> None:
    resp = ModelsListResponse()
    assert resp.object == "list"
    assert resp.data == []
    assert resp.ids == []


def test_models_list_ids_property() -> None:
    resp = ModelsListResponse.model_validate(
        {
            "object": "list",
            "data": [
                {"id": "a"},
                {"id": "b", "type": "llm", "max_context_length": 8192},
            ],
        }
    )
    assert resp.ids == ["a", "b"]
    assert resp.data[1].max_context_length == 8192


def test_models_list_ignores_envelope_extras() -> None:
    resp = ModelsListResponse.model_validate(
        {"status": True, "object": "list", "data": [{"id": "x"}]}
    )
    assert resp.ids == ["x"]


# ---------------------------------------------------------------------- #
# conversation
# ---------------------------------------------------------------------- #


def test_conversation_responses() -> None:
    for cls in (ConversationResponse, ExtendedConversationResponse):
        assert cls().response is None
        assert cls(response="hi").response == "hi"


# ---------------------------------------------------------------------- #
# per-text list outputs
# ---------------------------------------------------------------------- #


def test_polarity_item_and_response() -> None:
    assert Polarity3cItem().original == ""
    assert Polarity3cItem().polarity == ""
    assert Polarity3cResponse().response == []
    resp = Polarity3cResponse.model_validate(
        {"response": [{"original": "a", "polarity": "positive"}]}
    )
    assert resp.response[0].polarity == "positive"


def test_translate_item_and_response() -> None:
    assert TranslateItem().original == ""
    assert TranslateItem().translated == ""
    assert TranslateResponse().response == []
    resp = TranslateResponse.model_validate(
        {"response": [{"original": "a", "translated": "b"}]}
    )
    assert resp.response[0].translated == "b"


def test_simplify_text_response_defaults_list() -> None:
    assert SimplifyTextResponse().response == []
    assert SimplifyTextResponse(response=["simple"]).response == ["simple"]


def test_text_questions_and_response() -> None:
    assert TextQuestions().text == ""
    assert TextQuestions().questions == []
    assert GenerateQuestionsResponse().response == []
    resp = GenerateQuestionsResponse.model_validate(
        {"response": [{"text": "t", "questions": ["q1", "q2"]}]}
    )
    assert resp.response[0].questions == ["q1", "q2"]


# ---------------------------------------------------------------------- #
# single-text outputs
# ---------------------------------------------------------------------- #


def test_generative_answer_and_label_responses() -> None:
    assert GenerativeAnswerResponse().response is None
    assert GenerativeAnswerResponse(response="ans").response == "ans"
    assert GenerateLabelResponse().response is None
    assert GenerateLabelResponse(response="label").response == "label"


# ---------------------------------------------------------------------- #
# article outputs (nested ArticleText with default_factory)
# ---------------------------------------------------------------------- #


def test_article_text_defaults() -> None:
    assert ArticleText().article_text is None
    assert ArticleText(article_text="body").article_text == "body"


def test_article_responses_default_to_empty_article_text() -> None:
    for cls in (
        GenerateArticleFromTextResponse,
        CreateFullArticleFromTextsResponse,
        GenerateArticleFromTextsResponse,
    ):
        resp = cls()
        assert isinstance(resp.response, ArticleText)
        assert resp.response.article_text is None


def test_article_response_parses_nested_payload() -> None:
    resp = GenerateArticleFromTextResponse.model_validate(
        {"generation_time": 2.0, "response": {"article_text": "article"}}
    )
    assert resp.generation_time == 2.0
    assert resp.response.article_text == "article"
