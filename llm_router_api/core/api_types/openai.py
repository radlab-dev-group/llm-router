from __future__ import annotations

import datetime
from dateutil import parser

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
        return self.chat_ep()

    def completions_method(self) -> str:
        return "POST"


class OpenAIConverters:
    class FromOllama:
        @staticmethod
        def convert(response):
            created_at = response.get("created_at")
            if not created_at:
                created_at = datetime.datetime.now().timestamp()
            else:
                created_at = parser.isoparse(created_at).timestamp()
            prompt_tokens = int(response.get("prompt_eval_count", 0))
            completion_tokens = int(response.get("eval_count", 0))

            return {
                "id": response.get("id"),
                "object": "chat.completion",
                "created": created_at,
                "model": response.get("model", ""),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response["message"]["content"],
                            "refusal": None,
                            "annotations": None,
                            "audio": None,
                            "function_call": None,
                            "tool_calls": [],
                            "reasoning_content": response["message"].get("thinking"),
                        },
                        "logprobs": None,
                        "finish_reason": response.get("done_reason", "stop"),
                        "stop_reason": None,
                        "token_ids": None,
                    }
                ],
                "service_tier": None,
                "system_fingerprint": None,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "completion_tokens": completion_tokens,
                    "prompt_tokens_details": None,
                },
                "prompt_logprobs": None,
                "prompt_token_ids": None,
                "kv_transfer_params": None,
            }
