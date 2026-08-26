"""
Data‑model definitions for the LLM‑Router API.

This subpackage provides Pydantic models used to describe every request payload
the router accepts (conversation, translation, article generation, etc.) as well
as shared configuration constants.  All public classes and constants are exported
via ``__all__`` so callers can import directly from the package root:

    from llm_router_lib.data_models import ConversationWithModelRequest

All model classes inherit from :class:`pydantic.BaseModel` and benefit from its
automatic validation, serialisation (``model_dump()``), and JSON schema support.
"""

from llm_router_lib.data_models.base_model import BaseModelOptions
from llm_router_lib.data_models.builtin_chat import (
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
)
from llm_router_lib.data_models.builtin_utils import (
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
)
from llm_router_lib.data_models.masker import BaseMaskerModel, FastMaskerModel
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
from llm_router_lib.data_models.openai import OpenAIChatModel

__all__ = [
    # Shared config
    "BaseModelOptions",
    # Conversation models
    "ConversationWithModelRequest",
    "ExtendedConversationWithModelRequest",
    "GENAI_CONV_REQ_ARGS",
    "GENAI_CONV_OPT_ARGS",
    "EXT_GENAI_CONV_REQ_ARGS",
    "EXT_GENAI_CONV_OPT_ARGS",
    # Utility models
    "Polarity3cModel",
    "POLARITY_3C_REQ",
    "POLARITY_3C_OPT",
    "TranslateModel",
    "SimplifyTextModel",
    "GenerateQuestionsModel",
    "GenerateArticleFromTextModel",
    "CreateFullArticleFromTextsModel",
    "GenerativeAnswerModel",
    "GENERATIVE_ANSWER_REQ",
    "GENERATIVE_ANSWER_OPT",
    "GenerateLabelModel",
    "GENERATE_LABEL_REQ",
    "GENERATE_LABEL_OPT",
    # Masker models
    "BaseMaskerModel",
    "FastMaskerModel",
    # OpenAI-compatible
    "OpenAIChatModel",
    # Response models
    "BaseResponse",
    "GenerationResponse",
    "PingResponse",
    "VersionResponse",
    "ModelInfo",
    "ModelsListResponse",
    "ConversationResponse",
    "ExtendedConversationResponse",
    "Polarity3cItem",
    "Polarity3cResponse",
    "TranslateItem",
    "TranslateResponse",
    "SimplifyTextResponse",
    "TextQuestions",
    "GenerateQuestionsResponse",
    "GenerativeAnswerResponse",
    "GenerateLabelResponse",
    "ArticleText",
    "GenerateArticleFromTextResponse",
    "CreateFullArticleFromTextsResponse",
    "GenerateArticleFromTextsResponse",
]
