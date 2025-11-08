from pydantic import BaseModel
from typing import List, Dict, Any

from llm_router_api.base.constants_base import DEFAULT_EP_LANGUAGE


class OpenAIChatModel(BaseModel):
    model: str
    messages: List[Dict[str, Any]]

    stream: bool = True
    keep_alive: str = "30m"
    language: str = DEFAULT_EP_LANGUAGE

    options: Dict[str, Any] = {"num_ctx": 128000}


OPENAI_CHAT_REQ_ARGS = ["model", "messages"]
OPENAI_CHAT_OPT_ARGS = ["stream", "keep_alive", "language", "options"]
