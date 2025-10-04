from __future__ import annotations

#
# from typing import Dict, List
# from pydantic import BaseModel

from llm_proxy_rest.core.api_types.types_i import ApiTypesI


class OllamaType(ApiTypesI):
    """
    Ollama API implementation.

    Endpoints are based on the Ollama HTTP API specification.
    """

    #
    # def models_list_ep(self) -> str:
    #     return "/api/tags"
    #
    # def models_list_method(self) -> str:
    #     return "GET"

    def chat_ep(self) -> str:
        return "/api/chat"

    def chat_method(self) -> str:
        return "POST"

    def completions_ep(self) -> str:
        return "/api/generate"

    def completions_method(self) -> str:
        return "POST"

    #
    # def params(self) -> List[str]:
    #     return [
    #         "model",
    #         "messages",  # chat
    #         "prompt",  # generate
    #         "stream",
    #         "options",  # temperature, top_p, etc.
    #         "format",  # json, etc.
    #         "keep_alive",
    #         "context",  # kv cache context
    #         "template",
    #         "tools",
    #         "tool_choice",
    #         "system",
    #         "max_tokens",
    #         "temperature",
    #         "top_p",
    #         "stop",
    #         "repeat_penalty",
    #         "presence_penalty",
    #         "frequency_penalty",
    #     ]
    #
    # def convert_params(self, model: BaseModel | Dict) -> Dict[str, object]:
    #     """
    #     Normalize a high-level model into an Ollama payload.
    #     """
    #     if isinstance(model, BaseModel):
    #         model = model.model_dump()
    #     #
    #     # # Minimal duck-typing to extract common fields
    #     # get = getattr
    #     # # Determine if it's chat-like (has messages) or prompt-like (has prompt/text)
    #     # messages = get(model, "messages", None)
    #     # prompt = get(model, "prompt", None) or get(model, "text", None)
    #     #
    #     # payload: Dict[str, object] = {
    #     #     "model": get(model, "model", None) or get(model, "model_name", None),
    #     #     "stream": get(model, "stream", False),
    #     # }
    #     #
    #     # # Common tuning mapped into options
    #     # options: Dict[str, object] = {}
    #     # for k_model, k_api in [
    #     #     ("temperature", "temperature"),
    #     #     ("top_p", "top_p"),
    #     #     ("top_k", "top_k"),
    #     #     ("max_tokens", "num_predict"),
    #     #     ("presence_penalty", "presence_penalty"),
    #     #     ("frequency_penalty", "frequency_penalty"),
    #     #     ("repeat_penalty", "repeat_penalty"),
    #     # ]:
    #     #     val = get(model, k_model, None)
    #     #     if val is not None:
    #     #         options[k_api] = val
    #     # if options:
    #     #     payload["options"] = options
    #     #
    #     # # Tools
    #     # tools = get(model, "tools", None)
    #     # if tools is not None:
    #     #     payload["tools"] = tools
    #     # tool_choice = get(model, "tool_choice", None)
    #     # if tool_choice is not None:
    #     #     payload["tool_choice"] = tool_choice
    #     #
    #     # # System/template
    #     # system = get(model, "system", None)
    #     # if system is not None:
    #     #     payload["system"] = system
    #     # template = get(model, "template", None)
    #     # if template is not None:
    #     #     payload["template"] = template
    #     #
    #     # # Stop sequences
    #     # stop = get(model, "stop", None)
    #     # if stop is not None:
    #     #     payload["stop"] = stop
    #     #
    #     # # Context / keep_alive
    #     # context = get(model, "context", None)
    #     # if context is not None:
    #     #     payload["context"] = context
    #     # keep_alive = get(model, "keep_alive", None)
    #     # if keep_alive is not None:
    #     #     payload["keep_alive"] = keep_alive
    #     #
    #     # # Branch by conversation vs generation
    #     # if messages:
    #     #     payload["messages"] = messages
    #     # else:
    #     #     payload["prompt"] = prompt or ""
    #     #
    #     # return {k: v for k, v in payload.items() if v is not None}
    #     return model
