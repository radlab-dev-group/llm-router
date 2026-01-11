"""
Anthropic API integration utilities.
"""

from __future__ import annotations

import datetime
from typing import Dict, Any, List, Optional
from llm_router_api.core.api_types.types_i import ApiTypesI


class AnthropicType(ApiTypesI):
    """
    Concrete descriptor for Anthropic endpoints.
    """

    def chat_ep(self) -> str:
        """
        Return the URL path for the Anthropic messages endpoint.
        """
        return "/v1/messages"

    def completions_ep(self) -> str:
        """
        Anthropic uses the messages endpoint for chat-like completions.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """
        Return the URL path for the responses endpoint.
        """
        return "v1/responses"

    def embeddings_ep(self) -> str:
        """
        Anthropic doesn't have a native public embeddings API in the same way,
        but we provide the endpoint for consistency if needed.
        """
        return "v1/embeddings"


class AnthropicConverters:
    """
    Namespace for payload-conversion utilities for Anthropic.
    """

    class FromOpenAI:
        """
        Converters from OpenAI format to Anthropic format.
        """

        @staticmethod
        def convert_payload(params: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert OpenAI-style chat completion parameters to Anthropic Messages API format.
            """
            openai_messages = params.get("messages", [])
            anthropic_messages = []
            system_prompt = None

            for msg in openai_messages:
                role = msg.get("role")
                content = msg.get("content")
                if role == "system":
                    system_prompt = content
                else:
                    # Anthropic expects 'user' or 'assistant'
                    anthropic_messages.append({"role": role, "content": content})

            anthropic_payload = {
                "model": params.get("model"),
                "messages": anthropic_messages,
                "max_tokens": params.get(
                    "max_tokens", 4096
                ),  # Required by Anthropic
            }

            if system_prompt:
                anthropic_payload["system"] = system_prompt

            # Transfer other common params
            if "stream" in params:
                anthropic_payload["stream"] = params["stream"]
            if "temperature" in params:
                anthropic_payload["temperature"] = params["temperature"]
            if "top_p" in params:
                anthropic_payload["top_p"] = params["top_p"]
            if "stop" in params:
                anthropic_payload["stop_sequences"] = (
                    params["stop"]
                    if isinstance(params["stop"], list)
                    else [params["stop"]]
                )

            return anthropic_payload

        @staticmethod
        def convert_response(response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert OpenAI-style Chat Completion response to Anthropic format.
            """
            choices = response.get("choices", [])
            content = []
            stop_reason = None
            if choices:
                msg = choices[0].get("message", {})
                text = msg.get("content", "")
                if text:
                    content.append({"type": "text", "text": text})
                stop_reason = choices[0].get("finish_reason")

            prompt_tokens = response.get("usage", {}).get("prompt_tokens", 0)
            completion_tokens = response.get("usage", {}).get("completion_tokens", 0)

            return {
                "id": response.get("id"),
                "type": "message",
                "role": "assistant",
                "content": content,
                "model": response.get("model", ""),
                "stop_reason": stop_reason,
                "usage": {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                },
            }

    class FromOllama:
        """
        Converters from Ollama response format to Anthropic format.
        """

        @staticmethod
        def convert_response(response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert Ollama chat response to Anthropic format.
            """
            msg = response.get("message", {})
            content = []
            text = msg.get("content", "")
            if text:
                content.append({"type": "text", "text": text})

            prompt_tokens = response.get("prompt_eval_count", 0)
            completion_tokens = response.get("eval_count", 0)

            return {
                "id": "ollama-" + str(int(datetime.datetime.now().timestamp())),
                "type": "message",
                "role": "assistant",
                "content": content,
                "model": response.get("model", ""),
                "stop_reason": "end_turn" if response.get("done") else None,
                "usage": {
                    "input_tokens": prompt_tokens,
                    "output_tokens": completion_tokens,
                },
            }
