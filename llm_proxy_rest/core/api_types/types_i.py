from __future__ import annotations

from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import Dict, List, Any


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
                out.setdefault(api_type, []).append(ApiTypesI.get_models_list(m))

        return out

    @staticmethod
    def get_models_list(m: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(m.get("name", "")),
            "name": str(m.get("name", "")),
            "model": str(m.get("name", "")),
            "object": "model",
            "owned_by": str(m.get("api_type", "") or ""),
            "input_size": int(m.get("input_size") or 0),
            "max_context_length": int(m.get("input_size") or 0),
            "root": str(m.get("name", "")),
            "host": str(m.get("api_host", "")),
            "path": str(m.get("model_path", "")),
            "type": "vllm",
            "publisher": str(m.get("api_type", "") or ""),
            "state": "not-loaded",
            "arch": str(m.get("name", "")),
            "compatibility_type": "mlx",
            "quantization": "4bit",
        }

    #
    # @abstractmethod
    # def models_list_ep(self) -> str:
    #     """
    #     Return the relative URL path for the models listing endpoint.
    #
    #     Returns
    #     -------
    #     str
    #         Endpoint path (e.g., "/v1/models").
    #     """
    #     raise NotImplementedError
    #
    # @abstractmethod
    # def models_list_method(self) -> str:
    #     """
    #     Return the HTTP method used by the models listing endpoint.
    #
    #     Returns
    #     -------
    #     str
    #         HTTP method name (e.g., "GET").
    #     """
    #     raise NotImplementedError

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

    #
    # @abstractmethod
    # def params(self) -> List[str]:
    #     """
    #     Return the list of accepted parameter names for this API type.
    #
    #     Notes
    #     -----
    #     This list represents the union of commonly supported parameters
    #     across endpoints for the given API type. Concrete implementations
    #     may tailor this to project needs.
    #
    #     Returns
    #     -------
    #     List[str]
    #         A list of parameter keys accepted by this API type.
    #     """
    #     raise NotImplementedError
    #
    # @abstractmethod
    # def convert_params(self, model: BaseModel | Dict) -> Dict[str, object]:
    #     """
    #     Convert a high-level model configuration into API-specific params.
    #
    #     The input `model` can be one of:
    #     - ExtendedGenerativeConversationModel
    #     - GenerativeConversationModel
    #     - GenerativeQAModel
    #     - GenerativeQuestionGeneratorModel
    #     - GenerativeArticleFromText
    #     - CreateArticleFromNewsList
    #     - TranslateTextModel
    #     - GenerativeSimplification
    #
    #     Returns
    #     -------
    #     Dict[str, object]
    #         Mapping ready to be sent as 'params' for the target API type.
    #     """
    #     raise NotImplementedError
