from __future__ import annotations

from typing import Dict, List
from pydantic import BaseModel

from llm_proxy_rest.core.api_types.types_i import ApiTypesI


class VllmType(ApiTypesI):
    """
    vLLM OpenAI-compatible API implementation.

    Endpoints follow the OpenAI-compatible server exposed by vLLM.
    """

    def models_list_ep(self) -> str:
        return "/v1/models"

    def models_list_method(self) -> str:
        return "GET"

    def chat_ep(self) -> str:
        return "/v1/chat/completions"

    def chat_method(self) -> str:
        return "POST"

    def completions_ep(self) -> str:
        return "/v1/completions"

    def completions_method(self) -> str:
        return "POST"

    def params(self) -> List[str]:
        return [
            # shared
            "model",
            "stream",
            "temperature",
            "top_p",
            "top_k",
            "max_tokens",
            "presence_penalty",
            "frequency_penalty",
            "stop",
            "stop_sequences",
            # chat-specific
            "messages",
            "tools",
            "tool_choice",
            "response_format",
            "logprobs",
            "top_logprobs",
            "seed",
            # completions-specific
            "prompt",
            "suffix",
            "logit_bias",
            "n",
            "best_of",
            "echo",
        ]

    def convert_params(self, model: BaseModel | Dict) -> Dict[str, object]:
        """
        Normalize high-level model into OpenAI-compatible payload (vLLM).
        """
        if isinstance(model, BaseModel):
            model = model.model_dump()

        # get = getattr
        # messages = get(model, "messages", None)
        # prompt = get(model, "prompt", None) or get(model, "text", None)
        #
        # payload: Dict[str, object] = {
        #     "model": get(model, "model", None) or get(model, "model_name", None),
        #     "stream": get(model, "stream", False),
        #     "temperature": get(model, "temperature", None),
        #     "top_p": get(model, "top_p", None),
        #     "top_k": get(model, "top_k", None),
        #     "max_tokens": get(model, "max_tokens", None),
        #     "presence_penalty": get(model, "presence_penalty", None),
        #     "frequency_penalty": get(model, "frequency_penalty", None),
        #     "stop": get(model, "stop", None),
        #     "seed": get(model, "seed", None),
        #     "logprobs": get(model, "logprobs", None),
        #     "top_logprobs": get(model, "top_logprobs", None),
        #     "n": get(model, "n", None),
        #     "best_of": get(model, "best_of", None),
        #     "logit_bias": get(model, "logit_bias", None),
        #     "response_format": get(model, "response_format", None),
        # }
        #
        # tools = get(model, "tools", None)
        # if tools is not None:
        #     payload["tools"] = tools
        # tool_choice = get(model, "tool_choice", None)
        # if tool_choice is not None:
        #     payload["tool_choice"] = tool_choice
        #
        # if messages:
        #     payload["messages"] = messages
        # else:
        #     payload["prompt"] = prompt or ""
        #     suffix = get(model, "suffix", None)
        #     if suffix is not None:
        #         payload["suffix"] = suffix
        #     echo = get(model, "echo", None)
        #     if echo is not None:
        #         payload["echo"] = echo
        #
        # # stop_sequences alias
        # stop_sequences = get(model, "stop_sequences", None)
        # if stop_sequences is not None:
        #     payload["stop"] = stop_sequences
        #
        # return {k: v for k, v in payload.items() if v is not None}
        return model

