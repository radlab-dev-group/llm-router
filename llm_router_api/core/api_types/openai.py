"""
OpenAI API helpers.

This module provides two main utilities for working with the OpenAI API
in the *llm‑router* code‑base:

1. **OpenAIApiType** – a concrete implementation of
   :class:`llm_router_api.core.api_types.types_i.ApiTypesI`.  It supplies the
   relative URL paths and HTTP verbs required to call the various OpenAI
   endpoints (chat completions, embeddings, etc.).

2. **OpenAIConverters** – a namespace that groups conversion helpers which
   translate third‑party payloads (currently Ollama) into a format that
   conforms to the OpenAI *Chat Completion* schema.  Adding support for new
   providers simply means adding a nested ``From<Provider>`` class with a
   static ``convert`` method.

Both utilities are deliberately lightweight and contain no external
dependencies beyond what the rest of the project already uses.
"""

from __future__ import annotations

import datetime
from dateutil import parser
from typing import Dict, Any, List, Optional

from llm_router_api.core.api_types.types_i import ApiTypesI

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

OPENAI_ACCEPTABLE_PARAMS = [
    "model",
    "messages",
    "stream",
    "reasoning_effort",
    "extra_body",
    "tools",
    "input",
    "tool_choice",
]
"""
List of request parameters that the OpenAI client recognises.

The list mirrors the official OpenAI specification and can be used for
validation or filtering of user‑provided dictionaries before they are sent
to the API.
"""


# ---------------------------------------------------------------------------
# API descriptor
# ---------------------------------------------------------------------------


class OpenAIApiType(ApiTypesI):
    """
    Concrete descriptor for OpenAI endpoints.

    The abstract base class :class:`~llm_router_api.core.api_types.types_i.ApiTypesI`
    defines a contract for obtaining endpoint URLs and HTTP methods.  This
    implementation supplies the *relative* paths used by the OpenAI service
    (the caller is responsible for prefixing them with the base URL
    ``https://api.openai.com``).

    The OpenAI service re‑uses the same endpoint for both chat‑based
    completions and standard completions; therefore :meth:`completions_ep`
    simply forwards to :meth:`chat_ep`.
    """

    def chat_ep(self) -> str:
        """
        Return the URL path for the *chat completions* endpoint.

        Returns
        -------
        str
            The relative path ``/v1/chat/completions``.
        """
        return "/v1/chat/completions"

    def completions_ep(self) -> str:
        """
        Return the URL path for the *standard completions* endpoint.

        OpenAI routes normal completions through the same endpoint as chat
        completions, so this method forwards to :meth:`chat_ep`.

        Returns
        -------
        str
            The same path as :meth:`chat_ep`.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """
        Return the URL path for the *responses* endpoint.

        Returns
        -------
        str
            The relative path ``/v1/responses``.
        """
        return "v1/responses"

    def embeddings_ep(self) -> str:
        """
        Return the URL path for the *embeddings* endpoint.

        Returns
        -------
        str
            The relative path ``v1/embeddings``.
        """
        return "v1/embeddings"


# ---------------------------------------------------------------------------
# Converters namespace
# ---------------------------------------------------------------------------


class OpenAIConverters:
    """
    Namespace for response‑conversion utilities.

    Each nested ``From<Provider>`` class knows how to translate a third‑party
    payload into a dictionary that matches the OpenAI *Chat Completion* schema.
    The static ``convert`` method is the entry point; an optional
    ``convert_embedding`` helper is provided for providers that expose
    embedding vectors.
    """

    class FromAnthropic:
        """
        Converters from Anthropic response format to OpenAI format.
        """

        @staticmethod
        def convert_response(response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert Anthropic Messages API response to OpenAI-style Chat Completion.
            """
            content_list = response.get("content", [])
            text_content = ""
            for item in content_list:
                if item.get("type") == "text":
                    text_content += item.get("text", "")

            prompt_tokens = response.get("usage", {}).get("input_tokens", 0)
            completion_tokens = response.get("usage", {}).get("output_tokens", 0)

            return {
                "id": response.get("id"),
                "object": "chat.completion",
                "created": int(datetime.datetime.now().timestamp()),
                "model": response.get("model", ""),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": text_content,
                        },
                        "finish_reason": response.get("stop_reason"),
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }

        @staticmethod
        def convert_stream_chunk(chunk: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """
            Convert Anthropic stream event to OpenAI-style chunk.
            """
            event_type = chunk.get("type")

            if event_type == "content_block_delta":
                delta = chunk.get("delta", {})
                if delta.get("type") == "text_delta":
                    return {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": delta.get("text")},
                                "finish_reason": None,
                            }
                        ]
                    }
            elif event_type == "message_delta":
                return {
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": chunk.get("delta", {}).get(
                                "stop_reason"
                            ),
                        }
                    ]
                }

            return None

    class FromOllama:
        """
        Converters for Ollama responses.

        The methods in this class assume that the incoming payload is a
        plain ``dict`` returned by Ollama's HTTP API.  Missing fields are
        handled gracefully and sensible defaults (e.g. the current timestamp)
        are supplied where required.
        """

        @staticmethod
        def convert_embedding(response: dict) -> dict:
            """
            Transform an Ollama *embedding* response to OpenAI format.

            Parameters
            ----------
            response : dict
                The raw Ollama payload.  Expected keys are:
                ``model`` (str) and ``embeddings`` (list of vectors).  Optional
                ``prompt_eval_count`` is used for the ``usage`` block.

            Returns
            -------
            dict
                A dictionary that follows the OpenAI *embeddings* response
                schema:

                - ``object`` – always ``"list"``.
                - ``data`` – a list of ``{"object": "embedding", "index": i,
                  "embedding": <vector>}`` items.
                - ``model`` – the model name taken from the input.
                - ``usage`` – token usage information (mirrored from the
                  Ollama request).

            Notes
            -----
            The OpenAI spec expects ``prompt_tokens`` and ``total_tokens``.
            Because Ollama only reports ``prompt_eval_count``, we duplicate that
            value for both fields.
            """
            _resp = {
                "object": "list",
                "data": [],
                "model": response["model"],
                "usage": {
                    "prompt_tokens": response["prompt_eval_count"],
                    "total_tokens": response["prompt_eval_count"],
                },
            }

            for idx, e in enumerate(response["embeddings"]):
                _e = {"object": "embedding", "index": idx, "embedding": e}
                _resp["data"].append(_e)

            return _resp

        @staticmethod
        def convert(response: dict) -> dict:
            """
            Convert an Ollama chat response to the OpenAI *Chat Completion* format.

            Parameters
            ----------
            response : dict
                The raw response dictionary from Ollama.  The function extracts
                the fields required by the OpenAI schema and supplies defaults
                for optional items.

            Returns
            -------
            dict
                A dictionary that complies with the OpenAI Chat Completion
                specification.  The structure contains:

                - ``id`` – the original Ollama request identifier (if present).
                - ``object`` – always ``"chat.completion"``.
                - ``created`` – Unix epoch timestamp (derived from ``created_at``
                  or the current time).
                - ``model`` – the model name.
                - ``choices`` – a list with a single element describing the
                  assistant's message, optional reasoning content, and finish
                  reason.
                - ``usage`` – token usage breakdown.
                - Several optional OpenAI fields set to ``None`` for forward
                  compatibility.

            Details
            -------
            * ``created`` – derived from ``created_at`` (ISO‑8601) when present,
              otherwise uses ``datetime.datetime.now().timestamp()``.
            * Token counts – ``prompt_eval_count`` maps to ``prompt_tokens`` and
              ``eval_count`` maps to ``completion_tokens``.
            * The ``choices[0]["message"]`` dictionary mirrors the OpenAI
              message object, exposing ``role``, ``content`` and a placeholder for
              future fields such as ``refusal`` or ``annotations``.
            * ``finish_reason`` defaults to ``"stop"`` when Ollama does not
              provide a ``done_reason``.
            """
            # -----------------------------------------------------------------
            # Timestamp handling
            # -----------------------------------------------------------------
            created_at = response.get("created_at")
            if not created_at:
                created_at = datetime.datetime.now().timestamp()
            else:
                # Parse ISO‑8601 string to a POSIX timestamp.
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
