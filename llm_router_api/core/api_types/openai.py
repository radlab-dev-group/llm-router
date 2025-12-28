from __future__ import annotations

import datetime
from dateutil import parser

from llm_router_api.core.api_types.types_i import ApiTypesI


OPENAI_ACCEPTABLE_PARAMS = [
    "model",
    "messages",
    "stream",
    "reasoning_effort",
    "extra_body",
    "tools",
    "tool_choice",
]


class OpenAIApiType(ApiTypesI):
    """
    Concrete API descriptor for OpenAI endpoints.
    The class implements the abstract methods defined in
    :class:`~llm_router_api.core.api_types.types_i.ApiTypesI`.  Each method
    returns the relative URL path (``*_ep``) or the HTTP verb (``*_method``) that
    should be used when invoking the corresponding OpenAI service.

    The OpenAI API treats ``/v1/chat/completions`` as the canonical endpoint
    for both chat‑based interactions and standard completions, which is why
    ``completions_ep`` simply forwards to ``chat_ep``.
    """

    #
    # def models_list_ep(self) -> str:
    #     return "/v1/models"
    #
    # def models_list_method(self) -> str:
    #     return "GET"

    def chat_ep(self) -> str:
        """
        Return the URL path for the chat completions endpoint.

            Returns
            -------
            str
                The relative path ``/v1/chat/completions``.
        """
        return "/v1/chat/completions"

    def chat_method(self) -> str:
        """
        Return the HTTP method used for the chat completions endpoint.

            Returns
            -------
            str
                ``"POST"``, as the OpenAI API expects a POST request for chat.
        """
        return "POST"

    def completions_ep(self) -> str:
        """
        Return the URL path for the completions' endpoint.

            The OpenAI service re‑uses the chat completions endpoint for standard
            completions, so this method simply forwards to :meth:`chat_ep`.

            Returns
            -------
            str
                The same path as :meth:`chat_ep`.
        """
        return self.chat_ep()

    def completions_method(self) -> str:
        """
        Return the HTTP method for the completions endpoint.

            Mirrors :meth:`chat_method` because both endpoints share the same verb.

            Returns
            -------
            str
                ``"POST"``
        """
        return "POST"


class OpenAIConverters:
    """
    Namespace for response‑conversion utilities.
    Converters transform third‑party payloads into a structure that conforms
    to the OpenAI Chat Completion schema.  Adding new providers is as simple
    as creating a nested ``From<Provider>`` class with a static ``convert``
    method.
    """

    class FromOllama:
        """
        Convert Ollama response objects to OpenAI‑compatible format.

           The conversion extracts the relevant fields, normalises timestamps to
           Unix epoch seconds, and builds the ``choices`` list expected by the
           OpenAI client libraries.  Missing fields fall back to sensible defaults
           (e.g. current time for ``created_at``).

           Notes
           -----
           * ``response`` is assumed to be a ``dict`` produced by Ollama's HTTP
             API.  Keys that are not present are handled gracefully.
           * The resulting dictionary mirrors the shape described in the
             `OpenAI Chat Completion`_ documentation.
        """

        @staticmethod
        def convert(response):
            """
            Convert an Ollama response to the OpenAI chat‑completion format.

                    Parameters
                    ----------
                    response : dict
                        The raw response dictionary returned by an Ollama request.

                    Returns
                    -------
                    dict
                        A dictionary that follows the OpenAI Chat Completion schema,
                        ready to be returned to a downstream consumer.

                    Details
                    -------
                    * ``created`` – Unix timestamp derived from ``created_at`` if
                      present; otherwise the current time.
                    * Token counts – ``prompt_eval_count`` maps to ``prompt_tokens`` and
                      ``eval_count`` maps to ``completion_tokens``.
                    * The ``choices`` list contains a single entry with the assistant's
                      message, optional reasoning content, and finish reason.
            """

            created_at = response.get("created_at")
            if not created_at:
                created_at = datetime.datetime.now().timestamp()
            else:
                created_at = parser.isoparse(created_at).timestamp()
            prompt_tokens = int(response.get("prompt_eval_count", 0))
            completion_tokens = int(response.get("eval_count", 0))

            return {
                "id": response.get("id"),
                "object": "chat.completion",
                "created": created_at,
                "model": response.get("model", ""),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response["message"]["content"],
                            "refusal": None,
                            "annotations": None,
                            "audio": None,
                            "function_call": None,
                            "tool_calls": [],
                            "reasoning_content": response["message"].get("thinking"),
                        },
                        "logprobs": None,
                        "finish_reason": response.get("done_reason", "stop"),
                        "stop_reason": None,
                        "token_ids": None,
                    }
                ],
                "service_tier": None,
                "system_fingerprint": None,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "completion_tokens": completion_tokens,
                    "prompt_tokens_details": None,
                },
                "prompt_logprobs": None,
                "prompt_token_ids": None,
                "kv_transfer_params": None,
            }
