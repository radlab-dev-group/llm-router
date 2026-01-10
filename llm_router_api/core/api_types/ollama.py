"""
Ollama API integration utilities.

This module supplies two primary building blocks for the *llm‑router* project:

1. **OllamaType** – a concrete implementation of
   :class:`llm_router_api.core.api_types.types_i.ApiTypesI`.  It maps the
   internal routing logic to the Ollama HTTP endpoints, exposing the relative
   URL paths required for chat, completions, responses, and embeddings.

2. **OllamaConverters** – a namespace that holds conversion helpers for
   translating payloads between the OpenAI and Ollama schemas.  Adding support
   for additional providers merely requires a new nested ``From<Provider>``
   class with a static ``convert`` (or ``convert_embedding``) method.

Both components are deliberately lightweight and type‑annotated to aid static
analysis tools such as ``mypy`` and IDEs like PyCharm.
"""

from __future__ import annotations

from llm_router_api.core.api_types.types_i import ApiTypesI


class OllamaType(ApiTypesI):
    """
    Concrete descriptor for Ollama endpoints.

    The abstract base class :class:`~llm_router_api.core.api_types.types_i.ApiTypesI`
    defines a contract for retrieving endpoint URLs and HTTP methods.  This
    implementation supplies the *relative* paths used by Ollama’s service
    (the caller is responsible for prefixing them with the appropriate base
    URL, e.g. ``http://localhost:11434``).

    Ollama re‑uses the same ``/api/chat`` endpoint for both chat‑based
    interactions and standard completions; consequently the ``completions_*``
    helpers delegate to the corresponding ``chat_*`` methods.
    """

    def chat_ep(self) -> str:
        """Return the URL path for Ollama’s chat endpoint.

        Returns
        -------
        str
            The relative path ``"/api/chat"``.
        """
        return "/api/chat"

    def completions_ep(self) -> str:
        """Return the URL path for the completions endpoint.

        Ollama uses the same endpoint as chat, so this method forwards to
        :meth:`chat_ep`.

        Returns
        -------
        str
            ``"/api/chat"``, identical to the chat endpoint.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """Return the URL path for the responses endpoint.

        Returns
        -------
        str
            The relative path ``/v1/responses``.
        """
        return "v1/responses"

    def embeddings_ep(self) -> str:
        """Return the URL path for the embeddings endpoint.

        Returns
        -------
        str
            ``"api/embed"``, the path used by Ollama to receive embedding
            vectors.
        """
        return "api/embed"


class OllamaConverters:
    """Namespace for payload‑conversion utilities.

    Nested ``From<Provider>`` classes convert third‑party responses into the
    shape expected by Ollama’s API.  At present only a conversion from the
    OpenAI embedding schema is provided, but the pattern easily extends to
    additional providers.
    """

    class FromOpenAI:
        """Converters for OpenAI‑style embedding responses."""

        @staticmethod
        def convert_embedding(response: dict) -> dict:
            """Translate an OpenAI embedding payload to Ollama’s format.

            Parameters
            ----------
            response : dict
                The OpenAI embedding response.  Expected keys include:

                - ``model`` (str): model identifier.
                - ``data`` (list): each item contains an ``embedding`` key.
                - ``usage`` (dict): token usage information.

            Returns
            -------
            dict
                A dictionary compatible with Ollama’s ``/api/embed`` endpoint,
                containing:

                - ``model`` – the model identifier.
                - ``embeddings`` – a list of embedding vectors.
                - ``prompt_eval_count`` – token count for the prompt.
                - ``total_tokens`` – total token count (prompt + completion).

            Notes
            -----
            OpenAI places embeddings under the ``"data"`` key, while Ollama
            expects a top‑level ``"embeddings"`` list.  The conversion extracts
            each vector, preserving order, and copies usage statistics into the
            fields Ollama expects.
            """
            # Extract the list of vectors from OpenAI's ``data`` payload.
            embeddings = [
                item.get("embedding", []) for item in response.get("data", [])
            ]

            # Map OpenAI's usage fields to Ollama's naming scheme.
            prompt_eval_count = response.get("usage", {}).get("prompt_tokens", 0)
            total_tokens = response.get("usage", {}).get("total_tokens", 0)

            return {
                "model": response.get("model", ""),
                "embeddings": embeddings,
                "prompt_eval_count": prompt_eval_count,
                "total_tokens": total_tokens,
            }
