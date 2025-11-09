from __future__ import annotations


from llm_router_api.core.api_types.types_i import ApiTypesI


class OllamaType(ApiTypesI):
    """
    Ollama API implementation.

    Endpoints are based on the Ollama HTTP API specification.
    """

    def chat_ep(self) -> str:
        return "/api/chat"

    def chat_method(self) -> str:
        return "POST"

    def completions_ep(self) -> str:
        return "/api/generate"

    def completions_method(self) -> str:
        return "POST"
