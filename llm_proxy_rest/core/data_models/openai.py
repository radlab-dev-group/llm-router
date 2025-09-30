from pydantic import BaseModel
from typing import List, Dict, Any

from llm_proxy_rest.base.constants import DEFAULT_EP_LANGUAGE


class OpenAIChatModel(BaseModel):
    model: str
    messages: List[Dict[str, Any]]

    stream: bool = True
    keep_alive: str = "30m"
    language: str = DEFAULT_EP_LANGUAGE

    options: Dict[str, Any] = {"num_ctx": 16384}


OPENAI_CHAT_REQ_ARGS = ["model", "messages"]
OPENAI_CHAT_OPT_ARGS = ["stream", "keep_alive", "language", "options"]
