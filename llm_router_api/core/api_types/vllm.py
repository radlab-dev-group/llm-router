"""
Module providing the vLLM API type implementation.
The :class:VllmType class describes the endpoint paths and HTTP methods required
to interact with a vLLM server that exposes an OpenAI‑compatible REST interface.
"""

from __future__ import annotations

from typing import Any, Dict

from llm_router_api.core.api_types.types_i import ApiTypesI


class VllmType(ApiTypesI):
    """Concrete API descriptor for vLLM.

    The class implements the abstract methods defined in
    :class:`~llm_router_api.core.api_types.types_i.ApiTypesI`.  Each method
    returns the relative URL path or HTTP verb required to call the
    corresponding vLLM service.
    """

    def chat_ep(self) -> str:
        """
        Return the URL path for the chat completions endpoint.

        The vLLM server mirrors the OpenAI chat endpoint.
        """
        return "v1/chat/completions"

    def completions_ep(self) -> str:
        """
        Return the HTTP method for the completions endpoint.

        Mirrors :meth:`chat_method` because the underlying HTTP verb is the same.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """
        Return the URL path for the responses' endpoint.

        Returns
        -------
        str
            The relative path ``/v1/responses``.
        """
        return "v1/responses"

    def embeddings_ep(self) -> str:
        """
        Return the URL path for the embeddings' endpoint.

        Returns
        -------
        str
            The relative path ``v1/embeddings``.
        """
        return "v1/embeddings"


class VLLMConverters:
    """
    Namespace for payload-conversion utilities for vLLM.
    """

    PARAMS_MAPPING_FROM_TO = [
        ["max_new_tokens", "max_tokens"],
        ["model_name", "model"],
        ["language", None],
    ]

    class Payload:
        @staticmethod
        def convert_payload(params: Dict[str, Any]) -> Dict[str, Any]:
            for f, t in VLLMConverters.PARAMS_MAPPING_FROM_TO:
                if f in params:
                    if t is not None:
                        params[t] = params[f]
                    params.pop(f)

            if "max_tokens" in params and params["max_tokens"] < 1:
                params.pop("max_tokens", None)
            return params
