from __future__ import annotations

from typing import Dict, Any
from abc import ABC, abstractmethod


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
        """
        Convert a raw model configuration dict into a normalized model descriptor.
            The OpenAI routing layer expects each model to be represented by a
            dictionary containing a fixed set of keys (``id``, ``name``, ``object``,
            ``owned_by`` …).  ``get_models_list`` extracts the relevant fields from
            the source configuration supplied by the user (or a configuration file)
            and populates missing entries with sensible defaults.

            Parameters
            ----------
            m : dict
                A single model configuration entry.  Expected keys include
                ``name``, ``api_type``, ``input_size``, ``api_host``, and
                ``model_path``.  Any missing keys are replaced with empty strings or
                zero values.

            Returns
            -------
            dict
                A normalized model description compatible with the internal API.
                Example output::

                    {
                        "id": "gpt-oss:20b",
                        "name": "gpt-oss:20b",
                        "model": "gpt-oss:20b",
                        "object": "model",
                        "owned_by": "ollama",
                        "input_size": 256000,
                        "max_context_length": 256000,
                        "root": "gpt-oss:20b",
                        "host": "https://api.example.com",
                        "path": "",
                        "type": "vllm",
                        "publisher": "ollama",
                        "state": "not-loaded",
                        "arch": "gpt-oss:20b",
                        "compatibility_type": "mlx",
                        "quantization": "4bit",
                    }

            Notes
            -----
            * The function does **not** perform any validation beyond basic type
              coercion; callers should ensure the input dictionary follows the
              expected schema.
            * The returned mapping mirrors the structure used by the OpenAI API
              client libraries, facilitating seamless integration downstream.
        """

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
