from typing import List, Dict, Optional

from llm_router_api.base.constants_base import DEFAULT_EP_LANGUAGE
from llm_router_lib.data_models.base_model import BaseModelOptions
from llm_router_lib.data_models.constants import (
    LANGUAGE_PARAM,
    MODEL_NAME_PARAM,
    SYSTEM_PROMPT,
)


class _GenerativeOptions(BaseModelOptions):
    temperature: float = 0.75
    max_new_tokens: int = 256

    top_k: int = 50
    top_p: float = 0.99
    typical_p: float = 1.0
    repetition_penalty: float = 1.2
    language: Optional[str] = DEFAULT_EP_LANGUAGE


class _GenerativeOptionsModel(_GenerativeOptions):
    model_name: str


class GenerativeConversationModel(_GenerativeOptionsModel):
    user_last_statement: str
    historical_messages: List[Dict[str, str]] = []


class ExtendedGenerativeConversationModel(GenerativeConversationModel):
    system_prompt: str


GENAI_REQ_ARGS_BASE = [MODEL_NAME_PARAM]
GENAI_OPT_ARGS_BASE = [
    "max_new_tokens",
    "top_k",
    "top_p",
    "temperature",
    "typical_p",
    "repetition_penalty",
    LANGUAGE_PARAM,
]

GENAI_CONV_REQ_ARGS = GENAI_REQ_ARGS_BASE + ["user_last_statement"]
GENAI_CONV_OPT_ARGS = GENAI_OPT_ARGS_BASE + ["historical_messages"]

EXT_GENAI_CONV_REQ_ARGS = GENAI_CONV_REQ_ARGS + [SYSTEM_PROMPT]
EXT_GENAI_CONV_OPT_ARGS = GENAI_CONV_OPT_ARGS
