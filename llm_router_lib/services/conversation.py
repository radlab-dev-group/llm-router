import abc
from typing import Dict, Any, Type

from llm_router_lib.data_models.builtin_chat import (
    GenerativeConversationModel,
    ExtendedGenerativeConversationModel,
)
from llm_router_lib.utils.http import HttpRequester
from llm_router_lib.exceptions import LLMRouterError


class _BaseConversationService(abc.ABC):
    endpoint: str = ""
    model_cls: Type[Any] = None

    def __init__(self, http: HttpRequester, logger):
        self.http = http
        self.logger = logger

    def call(self, raw_payload: Any) -> Dict[str, Any]:
        resp = self.http.post(self.endpoint, json=raw_payload)
        try:
            j = resp.json()
        except Exception as exc:
            raise LLMRouterError(f"Invalid response format: {exc}")
        return j


class ConversationService(_BaseConversationService):
    endpoint = "/api/conversation_with_model"
    model_cls = GenerativeConversationModel


class ExtendedConversationService(_BaseConversationService):
    endpoint = "/api/extended_conversation_with_model"
    model_cls = ExtendedGenerativeConversationModel
