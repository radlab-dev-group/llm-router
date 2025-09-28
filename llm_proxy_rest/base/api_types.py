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

from abc import ABC, abstractmethod
from typing import Dict, Type


class _ApiTypes:
    class ApiTypesI(ABC):
        """
        Abstract base class describing endpoints and HTTP methods for an API type.

        Subclasses must implement:
        - models_list_ep() and models_list_method()
        - chat_ep() and chat_method()
        - completions_ep() and completions_method()
        """

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
