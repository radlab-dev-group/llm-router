"""
Ollama API integration utilities. This module defines :class:`OllamaType`,
a concrete implementation of :class:`~llm_router_api.core.api_types.types_i.ApiTypesI`
that maps the internal routing logic to the Ollama HTTP API endpoints.
"""

from __future__ import annotations

from llm_router_api.core.api_types.types_i import ApiTypesI


class OllamaType(ApiTypesI):
    """
    Concrete API descriptor for Ollama endpoints.

    The methods return the relative URL paths and HTTP verbs required to
    interact with Ollama's chat and completion routes.  Ollama re‑uses the
    same ``/api/chat`` endpoint for both chat and completion requests,
    therefore the ``completions_*`` helpers delegate to their chat
    counterparts.
    """

    def chat_ep(self) -> str:
        """
        Return the URL path for Ollama's chat endpoint.

        Returns
        -------
        str
            ``"/api/chat"``
        """
        return "/api/chat"

    def completions_ep(self) -> str:
        """
        Return the URL path for the completions' endpoint.

        Ollama uses the same endpoint as chat, so this forwards to
        :meth:`chat_ep`.

        Returns
        -------
        str
            ``"/api/chat"``
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
            ``"api/embed"``
        """
        return "api/embed"


class OllamaConverters:
    class FromOpenAI:
        @staticmethod
        def convert_embedding(response):
            """
            Convert an OpenAI‑style embedding response into the format expected by
            Ollama's ``/api/embed`` endpoint.

            Parameters
            ----------
            response : dict
                The OpenAI embedding payload (e.g. the JSON you posted).

            Returns
            -------
            dict
                A dictionary compatible with Ollama's embedding API, containing:
                - ``model`` – the model identifier,
                - ``embeddings`` – a list of embedding vectors,
                - ``prompt_eval_count`` – token count for the prompt,
                - ``total_tokens`` – total token count (prompt + completion).
            """
            # OpenAI returns embeddings under the "data" key.
            # Ollama expects a top‑level "embeddings" list and usage fields.
            _resp = {
                "model": response.get("model", ""),
                "embeddings": [
                    item.get("embedding", []) for item in response.get("data", [])
                ],
                "prompt_eval_count": response.get("usage", {}).get(
                    "prompt_tokens", 0
                ),
                "total_tokens": response.get("usage", {}).get("total_tokens", 0),
            }
            return _resp
