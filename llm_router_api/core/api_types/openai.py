from __future__ import annotations

from llm_router_api.core.api_types.types_i import ApiTypesI


OPENAI_ACCEPTABLE_PARAMS = [
    "model",
    "messages",
    "stream",
    "reasoning_effort",
    "extra_body",
    "tools",
    "tool_choice",
]


class OpenAIApiType(ApiTypesI):
    """
    OpenAI API implementation.

    Endpoints match OpenAI REST API paths.
    """

    #
    # def models_list_ep(self) -> str:
    #     return "/v1/models"
    #
    # def models_list_method(self) -> str:
    #     return "GET"

    def chat_ep(self) -> str:
        return "/v1/chat/completions"

    def chat_method(self) -> str:
        return "POST"

    def completions_ep(self) -> str:
        return "/v1/completions"

    def completions_method(self) -> str:
        return "POST"
