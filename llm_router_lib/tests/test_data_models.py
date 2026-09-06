"""
Unit tests for the request-side Pydantic data models in
``llm_router_lib.data_models`` — shared options, the built-in chat and
utility request models, the masker models, the OpenAI-compatible model, and
the string constants.

Focus is on defaults, required-field validation and serialisation
(``model_dump``) so the payload contract the client sends is pinned down.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_router_lib.core import constants as core_const
from llm_router_lib.data_models import (
    BaseModelOptions,
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
    Polarity3cModel,
    POLARITY_3C_REQ,
    POLARITY_3C_OPT,
    TranslateModel,
    SimplifyTextModel,
    GenerateQuestionsModel,
    GenerateArticleFromTextModel,
    CreateFullArticleFromTextsModel,
    GenerativeAnswerModel,
    GENERATIVE_ANSWER_REQ,
    GENERATIVE_ANSWER_OPT,
    GenerateLabelModel,
    GENERATE_LABEL_REQ,
    GENERATE_LABEL_OPT,
    BaseMaskerModel,
    FastMaskerModel,
    OpenAIChatModel,
)
from llm_router_lib.data_models.builtin_chat import (
    GenerativeOptions,
    GenerativeOptionsModel,
)
from llm_router_lib.data_models import constants as dm_const


# ---------------------------------------------------------------------- #
# BaseModelOptions
# ---------------------------------------------------------------------- #


def test_base_model_options_defaults() -> None:
    opts = BaseModelOptions()
    assert opts.mask_payload is False
    assert opts.masker_pipeline is None


def test_base_model_options_accepts_overrides() -> None:
    opts = BaseModelOptions(mask_payload=True, masker_pipeline=["fast"])
    assert opts.mask_payload is True
    assert opts.masker_pipeline == ["fast"]
    assert opts.model_dump() == {"mask_payload": True, "masker_pipeline": ["fast"]}


# ---------------------------------------------------------------------- #
# GenerativeOptions / GenerativeOptionsModel
# ---------------------------------------------------------------------- #


def test_generative_options_defaults_match_core_constants() -> None:
    o = GenerativeOptions()
    assert o.temperature == core_const.DEFAULT_TEMPERATURE
    assert o.max_new_tokens == core_const.DEFAULT_MAX_NEW_TOKENS
    assert o.top_k == core_const.DEFAULT_TOP_K
    assert o.top_p == core_const.DEFAULT_TOP_P
    assert o.typical_p == core_const.DEFAULT_TYPICAL_P
    assert o.repetition_penalty == core_const.DEFAULT_REPETITION_PENALTY
    assert o.language == core_const.DEFAULT_EP_LANGUAGE


def test_generative_options_model_requires_model_name() -> None:
    with pytest.raises(ValidationError):
        GenerativeOptionsModel()
    m = GenerativeOptionsModel(model_name="gemma")
    assert m.model_name == "gemma"


# ---------------------------------------------------------------------- #
# conversation models
# ---------------------------------------------------------------------- #


def test_conversation_with_model_request_minimal() -> None:
    req = ConversationWithModelRequest(model_name="m", user_last_statement="hello")
    assert req.historical_messages == []
    dumped = req.model_dump()
    assert dumped["model_name"] == "m"
    assert dumped["user_last_statement"] == "hello"
    assert dumped["historical_messages"] == []


def test_conversation_with_model_request_requires_fields() -> None:
    with pytest.raises(ValidationError):
        ConversationWithModelRequest(model_name="m")
    with pytest.raises(ValidationError):
        ConversationWithModelRequest(user_last_statement="hi")


def test_extended_conversation_requires_system_prompt() -> None:
    with pytest.raises(ValidationError):
        ExtendedConversationWithModelRequest(
            model_name="m", user_last_statement="hi"
        )
    req = ExtendedConversationWithModelRequest(
        model_name="m", user_last_statement="hi", system_prompt="be brief"
    )
    assert req.system_prompt == "be brief"


def test_conversation_arg_constants() -> None:
    assert "model_name" in GENAI_CONV_REQ_ARGS
    assert "user_last_statement" in GENAI_CONV_REQ_ARGS
    assert "historical_messages" in GENAI_CONV_OPT_ARGS
    assert "system_prompt" in EXT_GENAI_CONV_REQ_ARGS
    assert set(GENAI_CONV_OPT_ARGS) <= set(EXT_GENAI_CONV_OPT_ARGS)


# ---------------------------------------------------------------------- #
# utility models
# ---------------------------------------------------------------------- #


def test_polarity_model_requires_texts() -> None:
    with pytest.raises(ValidationError):
        Polarity3cModel(model_name="m")
    req = Polarity3cModel(model_name="m", texts=["a", "b"])
    assert req.texts == ["a", "b"]
    assert "texts" in POLARITY_3C_REQ


def test_translate_and_simplify_require_texts() -> None:
    for model_cls in (TranslateModel, SimplifyTextModel):
        with pytest.raises(ValidationError):
            model_cls(model_name="m")
        assert model_cls(model_name="m", texts=["x"]).texts == ["x"]


def test_generate_questions_defaults_number_of_questions() -> None:
    req = GenerateQuestionsModel(model_name="m", texts=["a"])
    assert req.number_of_questions == 1
    assert (
        GenerateQuestionsModel(
            model_name="m", texts=["a"], number_of_questions=3
        ).number_of_questions
        == 3
    )


def test_generate_article_from_text_requires_text() -> None:
    with pytest.raises(ValidationError):
        GenerateArticleFromTextModel(model_name="m")
    assert GenerateArticleFromTextModel(model_name="m", text="t").text == "t"


def test_create_full_article_requires_user_query_texts_optional() -> None:
    with pytest.raises(ValidationError):
        CreateFullArticleFromTextsModel(model_name="m")
    req = CreateFullArticleFromTextsModel(model_name="m", user_query="write")
    assert req.texts is None
    assert req.article_type is None


def test_generative_answer_requires_question_and_texts() -> None:
    with pytest.raises(ValidationError):
        GenerativeAnswerModel(model_name="m", question_str="q")
    with pytest.raises(ValidationError):
        GenerativeAnswerModel(model_name="m", texts=["t"])
    req = GenerativeAnswerModel(model_name="m", question_str="q", texts=["t"])
    assert req.doc_name_in_answer is False
    assert req.question_prompt is None
    assert "question_str" in GENERATIVE_ANSWER_REQ
    assert "texts" in GENERATIVE_ANSWER_REQ


def test_generate_label_requires_texts() -> None:
    with pytest.raises(ValidationError):
        GenerateLabelModel(model_name="m")
    assert "texts" in GENERATE_LABEL_REQ
    assert GENERATE_LABEL_OPT


# ---------------------------------------------------------------------- #
# masker models
# ---------------------------------------------------------------------- #


def test_base_masker_requires_text() -> None:
    with pytest.raises(ValidationError):
        BaseMaskerModel()
    assert BaseMaskerModel(text="secret").text == "secret"


def test_fast_masker_is_a_base_masker() -> None:
    assert issubclass(FastMaskerModel, BaseMaskerModel)
    m = FastMaskerModel(text="x")
    assert isinstance(m, BaseMaskerModel)
    assert m.text == "x"


# ---------------------------------------------------------------------- #
# OpenAI-compatible model
# ---------------------------------------------------------------------- #


def test_openai_chat_requires_model_and_messages() -> None:
    with pytest.raises(ValidationError):
        OpenAIChatModel(model="m")
    with pytest.raises(ValidationError):
        OpenAIChatModel(messages=[{"role": "user", "content": "hi"}])


def test_openai_chat_defaults() -> None:
    req = OpenAIChatModel(model="gpt", messages=[{"role": "user", "content": "hi"}])
    assert req.stream is True
    assert req.keep_alive == core_const.DEFAULT_KEEP_ALIVE
    assert req.language == core_const.DEFAULT_EP_LANGUAGE
    assert req.options == core_const.DEFAULT_OPTIONS
    assert req.mask_payload is False  # inherited from BaseModelOptions


def test_openai_chat_options_default_not_shared() -> None:
    # The DEFAULT_OPTIONS constant must not be aliased into instances.
    a = OpenAIChatModel(model="m", messages=[])
    b = OpenAIChatModel(model="m", messages=[])
    a.options["num_ctx"] = 1
    assert b.options["num_ctx"] == core_const.DEFAULT_OPTIONS["num_ctx"]


# ---------------------------------------------------------------------- #
# data-model string constants
# ---------------------------------------------------------------------- #


def test_string_constants() -> None:
    assert dm_const.LANGUAGE_PARAM == "language"
    assert dm_const.SYSTEM_PROMPT == "system_prompt"
    assert dm_const.MODEL_NAME_PARAM == "model_name"
    assert set(dm_const.MODEL_NAME_PARAMS) == {"model_name", "model"}
    assert set(dm_const.CLEAR_PREDEFINED_PARAMS) == {
        "response_time",
        "mask_payload",
        "masker_pipeline",
    }
