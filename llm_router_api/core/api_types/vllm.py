from __future__ import annotations

from llm_router_api.core.api_types.types_i import ApiTypesI


class VllmType(ApiTypesI):
    """
    vLLM OpenAI-compatible API implementation.

    Endpoints follow the OpenAI-compatible server exposed by vLLM.
    """

    def chat_ep(self) -> str:
        return "/v1/chat/completions"

    def chat_method(self) -> str:
        return "POST"

    def completions_ep(self) -> str:
        return self.chat_ep()

    def completions_method(self) -> str:
        return "POST"
