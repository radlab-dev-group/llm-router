"""
Ollama API integration utilities. This module defines :class:OllamaType,
a concrete implementation of :class:~llm_router_api.core.api_types.types_i.ApiTypesI
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

    def chat_method(self) -> str:
        """
        Return the HTTP method used for the chat endpoint.

            Returns
            -------
            str
                ``"POST"``
        """
        return "POST"

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

    def completions_method(self) -> str:
        """
        Return the HTTP method for the completions' endpoint.

            Mirrors :meth:`chat_method` because the underlying HTTP verb is the same.

            Returns
            -------
            str
                ``"POST"``
        """

        return "POST"
