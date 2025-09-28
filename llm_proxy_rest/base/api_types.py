"""
API types interface, dispatcher, and concrete implementations.

This module defines:
- ApiTypesI: an abstract base class describing the contract for API type
  implementations. It specifies methods for retrieving endpoint paths and
  HTTP methods for model listing, chat, and completion endpoints.
- OllamaType, VllmType, OpenAIApiType: concrete implementations returning
  endpoint paths and HTTP methods appropriate for each API type.
- ApiTypes: a lightweight dispatcher that exposes the same methods as
  ApiTypesI but accepts an `api_type` string and delegates to the
  appropriate concrete implementation.
"""

from __future__ import annotations

from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import Dict, Type, List, Any


class _ApiTypes:
    class ApiTypesI(ABC):
        """
        Abstract base class describing endpoints and HTTP methods for an API type.

        Subclasses must implement:
        - models_list_ep() and models_list_method()
        - chat_ep() and chat_method()
        - completions_ep() and completions_method()
        """

        @staticmethod
        def tags(models_config: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert the provided config dict with keys like "google_models",
            "openai_models", etc. into standardized lists per api_type.

            Input schema example:
            {
                "google_models": [
                    {
                        "api_host": "...",
                        "api_token": "",
                        "api_type": "vllm",
                        "input_size": 4096,
                        "model_path": "",
                        "name": "google/gemma-3-12b-it"
                    }, ...
                ],
                "openai_models": [
                    {
                        "api_host": "...",
                        "api_token": "",
                        "api_type": "ollama",
                        "input_size": 256000,
                        "model_path": "",
                        "name": "gpt-oss:20b"
                    }
                ]
            }

            Output:
            {
                "<api_type>": [
                    {
                        "id": "<name>",
                        "object": "model",
                        "owned_by": "<api_type>",
                         "input_size": <int>,
                         "root": "<name>",
                         "host": "<api_host>",
                         "path": "<model_path>"
                    },
                    ...
                ]
            }
            """

            def to_entry(m: Dict[str, Any]) -> Dict[str, Any]:
                return {
                    "id": str(m.get("name", "")),
                    "name": str(m.get("name", "")),
                    "model": str(m.get("name", "")),
                    "object": "model",
                    "owned_by": str(m.get("api_type", "") or ""),
                    "input_size": int(m.get("input_size") or 0),
                    "root": str(m.get("name", "")),
                    "host": str(m.get("api_host", "")),
                    "path": str(m.get("model_path", "")),
                }

            out: Dict[str, Any] = {}
            # Flatten all groups in the incoming dict and bucket by api_type
            for _, models_list in (models_config or {}).items():
                if not isinstance(models_list, list):
                    continue
                for m in models_list:
                    if not isinstance(m, dict):
                        continue
                    api_type = str(m.get("api_type", "")).lower()
                    if not api_type:
                        continue
                    out.setdefault(api_type, []).append(to_entry(m))

            return out

        @abstractmethod
        def models_list_ep(self) -> str:
            """
            Return the relative URL path for the models listing endpoint.

            Returns
            -------
            str
                Endpoint path (e.g., "/v1/models").
            """
            raise NotImplementedError

        @abstractmethod
        def models_list_method(self) -> str:
            """
            Return the HTTP method used by the models listing endpoint.

            Returns
            -------
            str
                HTTP method name (e.g., "GET").
            """
            raise NotImplementedError

        @abstractmethod
        def chat_ep(self) -> str:
            """
            Return the relative URL path for the chat endpoint.

            Returns
            -------
            str
                Endpoint path (e.g., "/v1/chat/completions").
            """
            raise NotImplementedError

        @abstractmethod
        def chat_method(self) -> str:
            """
            Return the HTTP method used by the chat endpoint.

            Returns
            -------
            str
                HTTP method name (e.g., "POST").
            """
            raise NotImplementedError

        @abstractmethod
        def completions_ep(self) -> str:
            """
            Return the relative URL path for the completion endpoint.

            Returns
            -------
            str
                Endpoint path (e.g., "/v1/completions").
            """
            raise NotImplementedError

        @abstractmethod
        def completions_method(self) -> str:
            """
            Return the HTTP method used by the completion endpoint.

            Returns
            -------
            str
                HTTP method name (e.g., "POST").
            """
            raise NotImplementedError

        @abstractmethod
        def params(self) -> List[str]:
            """
            Return the list of accepted parameter names for this API type.

            Notes
            -----
            This list represents the union of commonly supported parameters
            across endpoints for the given API type. Concrete implementations
            may tailor this to project needs.

            Returns
            -------
            List[str]
                A list of parameter keys accepted by this API type.
            """
            raise NotImplementedError

        @abstractmethod
        def convert_params(self, model: BaseModel | Dict) -> Dict[str, object]:
            """
            Convert a high-level model configuration into API-specific params.

            The input `model` can be one of:
            - ExtendedGenerativeConversationModel
            - GenerativeConversationModel
            - GenerativeQAModel
            - GenerativeQuestionGeneratorModel
            - GenerativeArticleFromText
            - CreateArticleFromNewsList
            - TranslateTextModel
            - GenerativeSimplification

            Returns
            -------
            Dict[str, object]
                Mapping ready to be sent as 'params' for the target API type.
            """
            raise NotImplementedError

    class OllamaType(ApiTypesI):
        """
        Ollama API implementation.

        Endpoints are based on the Ollama HTTP API specification.
        """

        def models_list_ep(self) -> str:
            return "/api/tags"

        def models_list_method(self) -> str:
            return "GET"

        def chat_ep(self) -> str:
            return "/api/chat"

        def chat_method(self) -> str:
            return "POST"

        def completions_ep(self) -> str:
            return "/api/generate"

        def completions_method(self) -> str:
            return "POST"

        def params(self) -> List[str]:
            return [
                "model",
                "messages",  # chat
                "prompt",  # generate
                "stream",
                "options",  # temperature, top_p, etc.
                "format",  # json, etc.
                "keep_alive",
                "context",  # kv cache context
                "template",
                "tools",
                "tool_choice",
                "system",
                "max_tokens",
                "temperature",
                "top_p",
                "stop",
                "repeat_penalty",
                "presence_penalty",
                "frequency_penalty",
            ]

        def convert_params(self, model: BaseModel | Dict) -> Dict[str, object]:
            """
            Normalize a high-level model into an Ollama payload.
            """
            if isinstance(model, BaseModel):
                model = model.model_dump()
            #
            # # Minimal duck-typing to extract common fields
            # get = getattr
            # # Determine if it's chat-like (has messages) or prompt-like (has prompt/text)
            # messages = get(model, "messages", None)
            # prompt = get(model, "prompt", None) or get(model, "text", None)
            #
            # payload: Dict[str, object] = {
            #     "model": get(model, "model", None) or get(model, "model_name", None),
            #     "stream": get(model, "stream", False),
            # }
            #
            # # Common tuning mapped into options
            # options: Dict[str, object] = {}
            # for k_model, k_api in [
            #     ("temperature", "temperature"),
            #     ("top_p", "top_p"),
            #     ("top_k", "top_k"),
            #     ("max_tokens", "num_predict"),
            #     ("presence_penalty", "presence_penalty"),
            #     ("frequency_penalty", "frequency_penalty"),
            #     ("repeat_penalty", "repeat_penalty"),
            # ]:
            #     val = get(model, k_model, None)
            #     if val is not None:
            #         options[k_api] = val
            # if options:
            #     payload["options"] = options
            #
            # # Tools
            # tools = get(model, "tools", None)
            # if tools is not None:
            #     payload["tools"] = tools
            # tool_choice = get(model, "tool_choice", None)
            # if tool_choice is not None:
            #     payload["tool_choice"] = tool_choice
            #
            # # System/template
            # system = get(model, "system", None)
            # if system is not None:
            #     payload["system"] = system
            # template = get(model, "template", None)
            # if template is not None:
            #     payload["template"] = template
            #
            # # Stop sequences
            # stop = get(model, "stop", None)
            # if stop is not None:
            #     payload["stop"] = stop
            #
            # # Context / keep_alive
            # context = get(model, "context", None)
            # if context is not None:
            #     payload["context"] = context
            # keep_alive = get(model, "keep_alive", None)
            # if keep_alive is not None:
            #     payload["keep_alive"] = keep_alive
            #
            # # Branch by conversation vs generation
            # if messages:
            #     payload["messages"] = messages
            # else:
            #     payload["prompt"] = prompt or ""
            #
            # return {k: v for k, v in payload.items() if v is not None}
            return model

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

    class OpenAIApiType(ApiTypesI):
        """
        OpenAI API implementation.

        Endpoints match OpenAI REST API paths.
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
                "max_tokens",
                "presence_penalty",
                "frequency_penalty",
                "stop",
                "logprobs",
                "top_logprobs",
                "logit_bias",
                "n",
                "user",
                "response_format",
                # chat-specific
                "messages",
                "tools",
                "tool_choice",
                "seed",
                # completions-specific
                "prompt",
                "suffix",
                "echo",
                "best_of",
            ]

        def convert_params(self, model: BaseModel | Dict) -> Dict[str, object]:
            """
            Normalize high-level model into OpenAI payload.
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
            #     "max_tokens": get(model, "max_tokens", None),
            #     "presence_penalty": get(model, "presence_penalty", None),
            #     "frequency_penalty": get(model, "frequency_penalty", None),
            #     "stop": get(model, "stop", None),
            #     "seed": get(model, "seed", None),
            #     "logprobs": get(model, "logprobs", None),
            #     "top_logprobs": get(model, "top_logprobs", None),
            #     "logit_bias": get(model, "logit_bias", None),
            #     "n": get(model, "n", None),
            #     "user": get(model, "user", None),
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
            #     best_of = get(model, "best_of", None)
            #     if best_of is not None:
            #         payload["best_of"] = best_of
            #
            # return {k: v for k, v in payload.items() if v is not None}
            return model


class ApiTypesDispatcher:
    """
    Dispatcher for API type implementations.

    This class exposes the same methods as `ApiTypesI`, but each method accepts
    a string `api_type` and delegates to the matching concrete implementation.

    Supported `api_type` values (case-insensitive):
    - "ollama"
    - "vllm"
    - "openai"
    """

    _REGISTRY: Dict[str, Type[_ApiTypes.ApiTypesI]] = {
        "ollama": _ApiTypes.OllamaType,
        "vllm": _ApiTypes.VllmType,
        "openai": _ApiTypes.OpenAIApiType,
    }

    @classmethod
    def _get_impl(cls, api_type: str) -> _ApiTypes.ApiTypesI:
        """
        Resolve and instantiate the concrete implementation for the given api_type.

        Parameters
        ----------
        api_type : str
            API type identifier.

        Returns
        -------
        _ApiTypes.ApiTypesI
            Concrete implementation instance.

        Raises
        ------
        ValueError
            If the api_type is not supported.
        """
        key = (api_type or "").strip().lower()
        impl = cls._REGISTRY.get(key)
        if impl is None:
            supported = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(
                f"Unsupported api_type '{api_type}'. Supported: {supported}"
            )
        return impl()

    # Endpoint paths
    @classmethod
    def models_list_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get models list endpoint path.
        """
        return cls._get_impl(api_type).models_list_ep()

    @classmethod
    def chat_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get chat endpoint path.
        """
        return cls._get_impl(api_type).chat_ep()

    @classmethod
    def completions_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get completion endpoint path.
        """
        return cls._get_impl(api_type).completions_ep()

    # HTTP methods
    @classmethod
    def models_list_method(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get models list HTTP method.
        """
        return cls._get_impl(api_type).models_list_method()

    @classmethod
    def chat_method(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get chat HTTP method.
        """
        return cls._get_impl(api_type).chat_method()

    @classmethod
    def completions_method(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get completion HTTP method.
        """
        return cls._get_impl(api_type).completions_method()

    @classmethod
    def params(cls, api_type: str) -> List[str]:
        """
        Delegate to the proper implementation to get an accepted params list.
        """
        return cls._get_impl(api_type).params()

    @classmethod
    def convert_params(
        cls, api_type: str, model: BaseModel | Dict
    ) -> Dict[str, object]:
        """
        Delegate to the proper implementation
        to convert a high-level model to params.
        """
        return cls._get_impl(api_type).convert_params(model)

    @classmethod
    def tags(
        cls, models_config: Dict[str, Any], merge_to_list: bool = True
    ) -> Dict[str, object] | List:
        all_tags = _ApiTypes.ApiTypesI.tags(models_config=models_config)
        if not merge_to_list:
            return all_tags

        res = []
        for models in all_tags.values():
            res.extend(models)
        return res
