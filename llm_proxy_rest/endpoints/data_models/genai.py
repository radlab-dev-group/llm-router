from pydantic import BaseModel
from typing import List, Dict


class _GenerativeOptions(BaseModel):
    temperature: float = 0.75
    max_new_tokens: int = 256

    top_k: int = 50
    top_p: float = 0.99
    typical_p: float = 1.0
    repetition_penalty: float = 1.2


class _GenerativeOptionsModel(_GenerativeOptions):
    model_name: str


class GenerativeConversationModel(_GenerativeOptionsModel):
    user_last_statement: str
    historical_messages: List[Dict[str, str]] = []


class ExtendedGenerativeConversationModel(GenerativeConversationModel):
    system_prompt: str


GENAI_REQ_ARGS_BASE = ["model_name"]
GENAI_OPT_ARGS_BASE = [
    "max_new_tokens",
    "top_k",
    "top_p",
    "temperature",
    "typical_p",
    "repetition_penalty",
]

GENAI_CONV_REQ_ARGS = GENAI_REQ_ARGS_BASE + ["user_last_statement"]
GENAI_CONV_OPT_ARGS = GENAI_OPT_ARGS_BASE

EXT_GENAI_CONV_REQ_ARGS = GENAI_CONV_REQ_ARGS + ["system_prompt"]
EXT_GENAI_CONV_OPT_ARGS = GENAI_CONV_OPT_ARGS
