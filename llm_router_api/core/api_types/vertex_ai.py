"""
Google Vertex AI (Gemini) API integration utilities.

The module provides two main utilities for working with Vertex AI in the
*llm‑router* code‑base:

1. **VertexAiType** – a concrete implementation of
   :class:`llm_router_api.core.api_types.types_i.ApiTypesI`.  Vertex AI uses
   a resource‑based REST model (``projects/{p}/locations/{l}/publishers/
   google/models/{m}:generateContent``), so the type overrides the request
   adapter hooks to build the resource path, the Google authentication
   headers and the native ``generateContent`` / ``streamGenerateContent`` /
   ``batchEmbedContents`` bodies.

2. **VertexAiConverters** – a namespace that groups conversion helpers
   translating between the OpenAI wire format (what the router's public
   endpoints speak) and the Gemini wire format (what Vertex AI speaks):
   request payloads, chat responses, SSE stream chunks and embeddings.

Both utilities are deliberately lightweight and contain no external
dependencies beyond what the rest of the project already uses
(``google-auth`` is optional and only touched when a provider relies on
Google Application Default Credentials).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from llm_router_api.core.api_types.auth.google import GoogleAccessTokenProvider
from llm_router_api.core.api_types.types_i import ApiTypesI

logger = logging.getLogger(__name__)

DEFAULT_API_VERSION = "v1"
DEFAULT_PUBLISHER = "google"

CHAT_OPERATION = ":generateContent"
STREAM_CHAT_OPERATION = ":streamGenerateContent?alt=sse"
EMBEDDINGS_OPERATION = ":batchEmbedContents"

#: ``image_url`` suffixes mapped to their MIME type (``fileData`` uploads).
_IMAGE_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

#: OpenAI JSON Schema type → Gemini ``Content`` type.
_SCHEMA_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
    "null": "NULL",
}


def _carry_thought_signature(
    part: Dict[str, Any], tool_call: Dict[str, Any]
) -> None:
    """
    Copy a thinking‑model ``thoughtSignature`` onto an OpenAI tool call.

    The signature is opaque and Gemini requires it to be echoed back on the
    next request turn, so it rides on the tool call as ``thought_signature``:
    an additive field, present only for models that actually produce one.
    """
    signature = part.get("thoughtSignature")
    if signature:
        tool_call["thought_signature"] = str(signature)


class VertexAiType(ApiTypesI):
    """
    Concrete descriptor for Google Vertex AI (Gemini) endpoints.

    The wire protocol is not OpenAI‑compatible: the model name lives in the
    URL resource, streaming uses ``streamGenerateContent`` with SSE, and the
    body is a ``generateContent`` request (``contents`` /
    ``systemInstruction`` / ``generationConfig``).  All of that is handled by
    the request‑adapter hooks, so the endpoint layer stays agnostic.
    """

    def chat_ep(self) -> str:
        """
        Return the chat operation suffix (``:generateContent``).
        """
        return CHAT_OPERATION

    def completions_ep(self) -> str:
        """
        Vertex AI serves completions through the chat operation.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """
        Vertex AI serves responses through the chat operation.
        """
        return self.chat_ep()

    def embeddings_ep(self) -> str:
        """
        Return the batch embeddings operation suffix.
        """
        return EMBEDDINGS_OPERATION

    # ------------------------------------------------------------------
    # Resource helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _provider_options(provider: Any) -> Dict[str, Any]:
        """
        Return the provider's ``provider_options`` mapping (empty when absent).
        """
        options = ApiTypesI._provider_field(provider, "provider_options", None)
        return dict(options) if isinstance(options, dict) else {}

    def _model_resource(self, provider: Any) -> str:
        """
        Build the model resource path (``publishers/{p}/models/{m}``).

        A ``model_path`` that already contains ``/models/`` is treated as a
        full resource and returned as‑is.
        """
        options = self._provider_options(provider)
        model = str(
            self._provider_field(provider, "model_path", "")
            or self._provider_field(provider, "name", "")
            or ""
        ).strip("/")
        if "/models/" in model:
            return model
        publisher = str(options.get("publisher") or DEFAULT_PUBLISHER).strip("/")
        return f"publishers/{publisher}/models/{model}"

    def _resource_path(self, provider: Any) -> str:
        """
        Return the model resource **path** (leading ``/``, no host).

        The ``v1/projects/{project}/locations/{region}`` prefix is appended
        only when the provider's ``api_host`` does not already carry a
        ``/projects/`` segment, so both configuration styles work:

        * ``api_host = https://REGION-aiplatform.googleapis.com`` with
          ``provider_options = {"project": ..., "region": ...}``;
        * ``api_host = https://REGION-aiplatform.googleapis.com/v1/
          projects/{p}/locations/{r}`` with (or without) the options.
        """
        api_host = str(self._provider_field(provider, "api_host", "") or "")
        parts: List[str] = []
        if "/projects/" not in api_host:
            options = self._provider_options(provider)
            project = str(options.get("project") or "").strip()
            region = str(
                options.get("region") or options.get("location") or ""
            ).strip()
            if project and region:
                api_version = str(
                    options.get("api_version") or DEFAULT_API_VERSION
                ).strip("/")
                parts.append(f"{api_version}/projects/{project}/locations/{region}")
        parts.append(self._model_resource(provider))
        return "/" + "/".join(parts)

    # ------------------------------------------------------------------
    # Request adapter hooks
    # ------------------------------------------------------------------
    def request_path(
        self,
        endpoint_url: str,
        provider: Any = None,
        stream: bool = False,
    ) -> str:
        """
        Build the Vertex resource path for the requested operation.
        """
        fragment = (endpoint_url or "").strip("/")
        if "embed" in fragment:
            operation = self.embeddings_ep()
        elif stream:
            operation = STREAM_CHAT_OPERATION
        else:
            operation = CHAT_OPERATION
        return self._resource_path(provider) + operation

    def request_headers(self, provider: Any) -> Dict[str, str]:
        """
        Build the Google authentication headers for ``provider``.

        Resolution order: ``api_token`` (``Bearer``) →
        ``provider_options.api_key`` (``x-goog-api-key``) → Google
        Application Default Credentials via
        :class:`GoogleAccessTokenProvider`.
        """
        headers = super().request_headers(provider)
        if self._provider_field(provider, "api_token", ""):
            return headers
        options = self._provider_options(provider)
        api_key = str(options.get("api_key") or "").strip()
        if api_key:
            headers["x-goog-api-key"] = api_key
            return headers
        token = GoogleAccessTokenProvider.get_token(options)
        headers["Authorization"] = f"Bearer {token}"
        return headers

    def request_body(
        self,
        payload: Any,
        provider: Any,
        system_message: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Translate an OpenAI‑style payload into a Vertex request body.
        """
        params = dict(payload or {})
        params.pop("stream", None)
        # Embeddings endpoints speak OpenAI (``input``), chat endpoints
        # speak ``messages``; the two never coexist in one payload.
        if "input" in params and "messages" not in params:
            return self._build_embedding_body(params, provider)
        if system_message:
            messages = list(params.get("messages") or [])
            messages.insert(0, dict(system_message))
            params["messages"] = messages
        return VertexAiConverters.Payload.convert_payload(params, provider=provider)

    def owns_message_normalization(self) -> bool:
        """
        The Gemini translator merges same‑role turns itself (keeping
        ``tool_call_id``), so the router's normaliser must not run first.
        """
        return True

    def ping_path(self, provider: Any) -> Optional[str]:
        """
        Health‑check probe: a ``GET`` on the model resource answers ``200``
        when the project, region, model and credentials are all valid.
        """
        return self._resource_path(provider)

    def on_response_status(self, provider: Any, status_code: int) -> None:
        """
        Evict a Google access token the upstream rejected.

        A ``401``/``403`` on a request authenticated through Application Default
        Credentials means the cached token went stale (revoked, clock skew,
        rotated service account); without the eviction every later request keeps
        replaying the same rejected token until the process restarts.  Tokens the
        operator manages directly (``api_token``, ``provider_options.api_key``)
        are left alone — the router's cache holds nothing to drop.
        """
        if status_code not in (401, 403):
            return
        if self._provider_field(provider, "api_token", ""):
            return
        options = self._provider_options(provider)
        if str(options.get("api_key") or "").strip():
            return
        GoogleAccessTokenProvider.invalidate(options)

    def _build_embedding_body(
        self, params: Dict[str, Any], provider: Any
    ) -> Dict[str, Any]:
        """
        Translate an OpenAI embeddings payload into
        ``batchEmbedContents`` (used for single and batch inputs alike).
        """
        inputs = params.get("input")
        if isinstance(inputs, str):
            inputs = [inputs]
        if not isinstance(inputs, list):
            inputs = [str(inputs)]

        resource = self._model_resource(provider)

        dimensions = params.get("dimensions")
        try:
            dimensions = int(dimensions) if dimensions else None
        except (TypeError, ValueError):
            dimensions = None

        requests_list = []
        for text in inputs:
            request: Dict[str, Any] = {
                "model": resource,
                "content": {"parts": [{"text": str(text)}]},
            }
            if dimensions:
                request["outputDimensionality"] = dimensions
            requests_list.append(request)
        return {"requests": requests_list}


class VertexAiConverters:
    """
    Namespace for payload‑conversion utilities for Google Vertex AI.

    Nested classes:

    * ``Payload`` – OpenAI request → Vertex ``generateContent`` body;
    * ``FromGemini`` – Vertex responses → OpenAI chat / stream / embeddings.
    """

    #: Vertex ``finishReason`` → OpenAI ``finish_reason``.
    FINISH_REASON_MAP = {
        "STOP": "stop",
        "MAX_TOKENS": "length",
        "SAFETY": "content_filter",
        "RECITATION": "content_filter",
        "PROHIBITED_CONTENT": "content_filter",
        "BLOCKLIST": "content_filter",
        "SPII": "content_filter",
        "FINISH_REASON_UNSPECIFIED": "stop",
    }

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    @classmethod
    def map_finish_reason(
        cls, finish_reason: Any, has_tool_calls: bool = False
    ) -> str:
        """
        Translate a Gemini ``finishReason`` into the OpenAI ``finish_reason``.

        Unknown or unmapped values (``MALFORMED_FUNCTION_CALL``, ``OTHER``,
        ``UNEXPECTED_TOOL_CALL``) collapse to ``"stop"`` rather than ``None``:
        a terminal chunk without a finish reason leaves OpenAI clients waiting
        for an end that never comes.  A turn that ended on a function call
        reports ``"tool_calls"``, which is what clients key off.
        """
        if has_tool_calls:
            return "tool_calls"
        mapped = cls.FINISH_REASON_MAP.get(str(finish_reason or ""))
        return mapped or "stop"

    @staticmethod
    def is_gemini_chat_response(payload: Dict[str, Any]) -> bool:
        """
        True when *payload* looks like a Vertex ``generateContent`` response.
        """
        return "candidates" in payload or "usageMetadata" in payload

    @staticmethod
    def is_gemini_embedding_response(payload: Dict[str, Any]) -> bool:
        """
        True when *payload* looks like a Vertex ``batchEmbedContents``
        response (``embeddings`` items carry a ``values`` key, unlike the
        Ollama list of vectors).
        """
        if "usageMetadata" in payload:
            return True
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            first = embeddings[0]
            return isinstance(first, dict) and "values" in first
        return False

    @staticmethod
    def _image_mime_type(url: str) -> str:
        suffix = url.rsplit(".", 1)[-1].lower() if "." in url else ""
        return _IMAGE_MIME_BY_EXT.get(suffix, "application/octet-stream")

    @staticmethod
    def _message_parts(content: Any) -> List[Dict[str, Any]]:
        """
        Convert an OpenAI message ``content`` (string or parts list) into
        Gemini ``parts`` (text, inline images, file‑URI images).
        """
        if content is None:
            return [{"text": ""}]
        if isinstance(content, str):
            return [{"text": content}]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        parts: List[Dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                parts.append({"text": item})
                continue
            if not isinstance(item, dict):
                logger.debug("Skipping non‑dict content part: %r", item)
                continue
            item_type = item.get("type")
            if item_type is None and "text" in item:
                item_type = "text"
            if item_type == "text":
                parts.append({"text": str(item.get("text", ""))})
            elif item_type == "image_url":
                url = (item.get("image_url") or {}).get("url") or ""
                if url.startswith("data:"):
                    header, _, b64 = url.partition(",")
                    mime = header[5:].split(";")[0] or "image/png"
                    parts.append({"inlineData": {"mimeType": mime, "data": b64}})
                elif url:
                    parts.append(
                        {
                            "fileData": {
                                "mimeType": VertexAiConverters._image_mime_type(url),
                                "fileUri": url,
                            }
                        }
                    )
            else:
                logger.debug("Skipping unsupported content part type: %r", item_type)
        return parts or [{"text": ""}]

    @staticmethod
    def _openai_schema_to_gemini(schema: Any) -> Dict[str, Any]:
        """
        Translate an OpenAI JSON Schema (function parameters) into a Gemini
        ``Content`` type.  ``$ref``/``$defs`` unions are not representable
        and degrade to a loose ``STRING``.
        """
        if not isinstance(schema, dict):
            return {"type": "STRING"}
        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            return {"type": "STRING"}
        out: Dict[str, Any] = {
            "type": _SCHEMA_TYPE_MAP.get(str(schema_type).lower(), "STRING")
        }
        if schema_type == "object":
            properties = schema.get("properties") or {}
            out["properties"] = {
                key: VertexAiConverters._openai_schema_to_gemini(value)
                for key, value in properties.items()
            }
            out["required"] = list(schema.get("required") or [])
        elif schema_type == "array":
            out["items"] = VertexAiConverters._openai_schema_to_gemini(
                schema.get("items") or {}
            )
        enum_values = schema.get("enum")
        if enum_values:
            out["enum"] = list(enum_values)
        return out

    @classmethod
    def _function_declarations(cls, tools: Any) -> List[Dict[str, Any]]:
        """
        Extract Gemini ``functionDeclarations`` from an OpenAI ``tools`` list.
        """
        declarations: List[Dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("type") not in (None, "function"):
                continue
            function = tool.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                continue
            declaration: Dict[str, Any] = {
                "name": function["name"],
            }
            if function.get("description"):
                declaration["description"] = function["description"]
            if function.get("parameters"):
                declaration["parameters"] = cls._openai_schema_to_gemini(
                    function["parameters"]
                )
            declarations.append(declaration)
        return declarations

    @classmethod
    def _tool_config(cls, tool_choice: Any) -> Optional[Dict[str, Any]]:
        """
        Translate an OpenAI ``tool_choice`` into a Gemini ``toolConfig``.
        """
        if tool_choice is None:
            return None
        if isinstance(tool_choice, str):
            mode = {
                "auto": "AUTO",
                "required": "ANY",
                "none": "NONE",
            }.get(tool_choice)
            if mode is None:
                return None
            return {"functionCallingConfig": {"mode": mode}}
        if isinstance(tool_choice, dict):
            if tool_choice.get("type") == "function":
                name = (tool_choice.get("function") or {}).get("name")
                if name:
                    return {
                        "functionCallingConfig": {
                            "mode": "ANY",
                            "allowedFunctionNames": [name],
                        }
                    }
        return None

    # ------------------------------------------------------------------
    # Request payload
    # ------------------------------------------------------------------
    class Payload:
        """
        Converters from OpenAI request format to Vertex format.
        """

        @classmethod
        def convert_payload(
            cls,
            params: Dict[str, Any],
            provider: Any = None,
        ) -> Dict[str, Any]:
            """
            Convert an OpenAI chat payload to a Vertex ``generateContent``
            body (``contents`` / ``systemInstruction`` / ``generationConfig``
            / ``tools`` / ``toolConfig`` / ``safetySettings``).

            Consecutive messages of the same (mapped) role are merged into a
            single Gemini turn — Vertex requires strictly alternating
            ``user`` / ``model`` turns, and merging keeps ``tool_call_id``
            information that the router‑level normaliser would lose.
            """
            params = dict(params or {})
            messages = params.get("messages") or []
            tool_names = cls._tool_call_names(messages)
            declarations = VertexAiConverters._function_declarations(
                params.get("tools")
            )
            if not declarations:
                cls._warn_orphan_tool_history(messages)

            contents: List[Dict[str, Any]] = []
            system_parts: List[Dict[str, Any]] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "user").lower()
                if role == "system":
                    system_parts.extend(cls._parts_for(message.get("content")))
                    continue
                gemini_role = "user"
                if role == "tool":
                    response_part = cls._tool_response_part(message, tool_names)
                    if response_part is None:
                        continue
                    parts = [response_part]
                elif role in ("assistant", "model"):
                    parts = cls._assistant_turn_parts(message)
                    gemini_role = "model"
                else:
                    parts = cls._parts_for(message.get("content"))
                if not parts:
                    continue
                if contents and contents[-1]["role"] == gemini_role:
                    contents[-1]["parts"].extend(parts)
                else:
                    contents.append({"role": gemini_role, "parts": parts})

            body: Dict[str, Any] = {"contents": contents}
            if system_parts:
                body["systemInstruction"] = {"parts": system_parts}

            generation_config = cls._generation_config(params, provider)
            if generation_config:
                body["generationConfig"] = generation_config

            options = (
                VertexAiType._provider_options(provider)
                if provider is not None
                else {}
            )
            safety_settings = options.get("safety_settings")
            if isinstance(safety_settings, list) and safety_settings:
                body["safetySettings"] = safety_settings

            if declarations:
                body["tools"] = [{"functionDeclarations": declarations}]
            tool_config = VertexAiConverters._tool_config(params.get("tool_choice"))
            if tool_config:
                body["toolConfig"] = tool_config
            return body

        @staticmethod
        def _parts_for(content: Any) -> List[Dict[str, Any]]:
            return VertexAiConverters._message_parts(content)

        # ------------------------------------------------------------------
        # Function‑calling helpers (OpenAI ``tool_calls`` ↔ Gemini parts)
        # ------------------------------------------------------------------
        @staticmethod
        def _tool_call_names(messages: List[Any]) -> Dict[str, str]:
            """
            Map ``tool_call.id`` → the function name the model actually called.

            Collected over the **whole** history, so a ``role: tool`` message is
            resolved no matter how far back its ``assistant`` message sits.
            """
            names: Dict[str, str] = {}
            for message in messages:
                if not isinstance(message, dict):
                    continue
                for tool_call in message.get("tool_calls") or []:
                    if not isinstance(tool_call, dict):
                        continue
                    call_id = str(tool_call.get("id") or "")
                    function = tool_call.get("function")
                    name = (
                        function.get("name") if isinstance(function, dict) else None
                    )
                    if call_id and name:
                        names[call_id] = str(name)
            return names

        @staticmethod
        def _parse_function_args(raw: Any, name: str = "") -> Dict[str, Any]:
            """
            Translate an OpenAI ``arguments`` value into a Gemini ``args`` mapping.

            Never raises and never invents argument keys: a fabricated key would
            not match the submitted ``functionDeclarations`` schema, so anything
            unusable degrades to ``{}`` with a warning.
            """
            if isinstance(raw, dict):
                return dict(raw)
            if raw is None or raw == "":
                return {}
            parsed: Any = None
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    parsed = None
            if isinstance(parsed, dict):
                return parsed
            logger.warning(
                "Could not parse arguments of function %r as a JSON object; "
                "sending empty args instead.",
                name or "unknown",
            )
            return {}

        @staticmethod
        def _thought_signature(tool_call: Dict[str, Any]) -> Optional[str]:
            """
            Read the thinking‑model signature carried on an OpenAI tool call.

            Accepts both the ``thought_signature`` spelling used in responses
            and the wire‑level ``thoughtSignature``.
            """
            signature = tool_call.get("thought_signature") or tool_call.get(
                "thoughtSignature"
            )
            return str(signature) if signature else None

        @classmethod
        def _function_call_parts(cls, tool_calls: Any) -> List[Dict[str, Any]]:
            """
            Convert OpenAI ``tool_calls`` into Gemini ``functionCall`` parts.

            ``thoughtSignature`` is attached **as a sibling of ``functionCall``**
            (where the Gemini ``Part`` carries it) and only when the upstream
            actually emitted one, so requests to models that never produce
            signatures stay byte‑identical.
            """
            parts: List[Dict[str, Any]] = []
            for tool_call in tool_calls or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict) or not function.get("name"):
                    continue
                name = str(function["name"])
                part: Dict[str, Any] = {
                    "functionCall": {
                        "name": name,
                        "args": cls._parse_function_args(
                            function.get("arguments"), name
                        ),
                    }
                }
                signature = cls._thought_signature(tool_call)
                if signature:
                    part["thoughtSignature"] = signature
                parts.append(part)
            return parts

        @classmethod
        def _assistant_turn_parts(
            cls, message: Dict[str, Any]
        ) -> List[Dict[str, Any]]:
            """
            Build the parts of one assistant turn: its text, then its calls.

            A pure tool‑call turn yields the ``functionCall`` parts only — an
            empty ``{"text": ""}`` part next to a call is what Gemini rejects.
            """
            content = message.get("content")
            parts: List[Dict[str, Any]] = []
            if content not in (None, "", []):
                parts.extend(cls._parts_for(content))
            parts.extend(cls._function_call_parts(message.get("tool_calls")))
            return parts or [{"text": ""}]

        @classmethod
        def _tool_response_part(
            cls, message: Dict[str, Any], names: Dict[str, str]
        ) -> Optional[Dict[str, Any]]:
            """
            Convert an OpenAI ``role: tool`` message into a ``functionResponse``.

            Returns ``None`` when the function cannot be identified: Gemini
            refuses a ``functionResponse`` whose name matches no submitted
            ``functionCall``, so a placeholder name would turn a salvageable
            request into a hard ``400`` — dropping the part degrades gracefully.
            """
            call_id = str(message.get("tool_call_id") or "")
            name = names.get(call_id) or str(message.get("name") or "")
            if not name:
                logger.warning(
                    "Dropping tool message with no matching function call "
                    "(tool_call_id=%r): Gemini requires functionResponse.name "
                    "to match a previously submitted functionCall.",
                    call_id or None,
                )
                return None
            return {
                "functionResponse": {
                    "name": name,
                    "response": {"content": message.get("content", "")},
                }
            }

        @staticmethod
        def _warn_orphan_tool_history(messages: List[Any]) -> None:
            """
            Warn when a tool history is sent to a provider with no ``tools``.

            ``EndpointWithHttpRequestI._prepare_params_for_provider`` strips
            ``tools`` from providers not declared as ``tool_calling``, which
            would otherwise leave ``functionCall`` parts pointing at undeclared
            functions.
            """
            for message in messages:
                if not isinstance(message, dict):
                    continue
                if message.get("tool_calls") or message.get("role") == "tool":
                    logger.warning(
                        "Conversation carries function calls but no tools were "
                        "declared for this Vertex request; Gemini will reject "
                        "the unmatched functionCall parts. Set "
                        '"tool_calling": true on the provider.'
                    )
                    return

        @staticmethod
        def _generation_config(
            params: Dict[str, Any], provider: Any
        ) -> Dict[str, Any]:
            """
            Build ``generationConfig`` from OpenAI sampling parameters and
            the operator's ``provider_options.generation_config`` overrides.
            """
            generation_config: Dict[str, Any] = {}
            if params.get("temperature") is not None:
                generation_config["temperature"] = params["temperature"]
            if params.get("top_p") is not None:
                generation_config["topP"] = params["top_p"]

            max_tokens = params.get(
                "max_tokens", params.get("max_completion_tokens")
            )
            if max_tokens is not None:
                try:
                    max_tokens = int(max_tokens)
                except (TypeError, ValueError):
                    max_tokens = None
                if max_tokens and max_tokens > 0:
                    generation_config["maxOutputTokens"] = max_tokens

            stop = params.get("stop")
            if stop:
                generation_config["stopSequences"] = (
                    stop if isinstance(stop, list) else [stop]
                )

            response_format = params.get("response_format")
            if (
                isinstance(response_format, dict)
                and response_format.get("type") == "json_object"
            ):
                generation_config["responseMimeType"] = "application/json"
                if response_format.get("schema"):
                    generation_config["responseSchema"] = response_format["schema"]

            options = (
                VertexAiType._provider_options(provider)
                if provider is not None
                else {}
            )
            overrides = options.get("generation_config")
            if isinstance(overrides, dict):
                generation_config.update(overrides)
            return generation_config

    # ------------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------------
    class FromGemini:
        """
        Converters from Vertex response format to OpenAI format.
        """

        @staticmethod
        def _usage(metadata: Any) -> Dict[str, Any]:
            usage = metadata if isinstance(metadata, dict) else {}
            prompt_tokens = int(usage.get("promptTokenCount") or 0)
            completion_tokens = int(usage.get("candidatesTokenCount") or 0)
            reasoning_tokens = int(usage.get("thoughtsTokenCount") or 0)
            total = int(
                usage.get("totalTokenCount")
                or prompt_tokens + completion_tokens + reasoning_tokens
            )
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
                "prompt_tokens_details": None,
                "completion_tokens_details": {
                    "reasoning_tokens": reasoning_tokens,
                },
            }

        @staticmethod
        def _function_calls(parts: List[Any]) -> List[Dict[str, Any]]:
            tool_calls: List[Dict[str, Any]] = []
            for index, part in enumerate(parts or []):
                if not isinstance(part, dict):
                    continue
                function_call = part.get("functionCall")
                if not function_call:
                    continue
                tool_call: Dict[str, Any] = {
                    "id": f"vertex_fc_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": function_call.get("name", ""),
                        "arguments": json.dumps(function_call.get("args") or {}),
                    },
                    "_index": index,
                }
                _carry_thought_signature(part, tool_call)
                tool_calls.append(tool_call)
            return tool_calls

        @classmethod
        def _strip_internal(cls, tool_calls: List[Dict[str, Any]]) -> None:
            for tool_call in tool_calls:
                tool_call.pop("_index", None)

        @classmethod
        def convert_response(cls, response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert a Vertex ``generateContent`` response to the OpenAI
            Chat Completion schema.
            """
            candidates = response.get("candidates") or []
            candidate = candidates[0] if candidates else {}
            parts = (candidate.get("content") or {}).get("parts") or []

            text = "".join(
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and "text" in part
            )
            tool_calls = cls._function_calls(parts)
            cls._strip_internal(tool_calls)

            finish_reason = None
            finish = candidate.get("finishReason")
            if finish:
                finish_reason = VertexAiConverters.map_finish_reason(
                    finish, bool(tool_calls)
                )

            return {
                "id": response.get("id") or f"vertex-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": response.get("modelVersion", ""),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": text,
                            "refusal": None,
                            "annotations": None,
                            "audio": None,
                            "function_call": None,
                            "tool_calls": tool_calls,
                            "reasoning_content": None,
                        },
                        "logprobs": None,
                        "finish_reason": finish_reason or "stop",
                        "stop_reason": None,
                        "token_ids": None,
                    }
                ],
                "service_tier": None,
                "system_fingerprint": None,
                "usage": cls._usage(response.get("usageMetadata")),
                "prompt_logprobs": None,
                "prompt_token_ids": None,
                "kv_transfer_params": None,
            }

        @staticmethod
        def new_stream_ctx(model: str = "") -> Dict[str, Any]:
            """
            Build the per‑stream conversion context for
            :meth:`convert_stream_chunk`.
            """
            return {
                "id": f"chatcmpl-vertex-{uuid.uuid4().hex[:24]}",
                "created": int(time.time()),
                "model": model or "",
                "started": False,
                "tool_seq": 0,
                "tool_call_seen": False,
            }

        @classmethod
        def new_final_chunk(
            cls, ctx: Dict[str, Any], finish_reason: str = "stop"
        ) -> Dict[str, Any]:
            """
            Build the terminal ``chat.completion.chunk`` of a converted stream.

            Used when the upstream Gemini SSE ended without a ``finishReason``
            so the client still receives a well‑formed end of turn.
            """
            return {
                "id": ctx["id"],
                "object": "chat.completion.chunk",
                "created": ctx["created"],
                "model": ctx["model"],
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish_reason}
                ],
            }

        @classmethod
        def convert_stream_chunk(
            cls, chunk: Dict[str, Any], ctx: Dict[str, Any]
        ) -> Optional[Dict[str, Any]]:
            """
            Convert one Vertex ``streamGenerateContent`` SSE payload into an
            OpenAI ``chat.completion.chunk`` (``None`` when nothing to emit).
            """
            candidates = chunk.get("candidates") or []
            if not candidates:
                # Final chunks may carry only ``usageMetadata``.
                if chunk.get("usageMetadata"):
                    return {
                        "id": ctx["id"],
                        "object": "chat.completion.chunk",
                        "created": ctx["created"],
                        "model": ctx["model"],
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": None}
                        ],
                        "usage": cls._usage(chunk.get("usageMetadata")),
                    }
                return None

            candidate = candidates[0]
            parts = (candidate.get("content") or {}).get("parts") or []
            model_version = chunk.get("modelVersion")
            if model_version:
                ctx["model"] = model_version

            delta: Dict[str, Any] = {}
            if not ctx["started"]:
                delta["role"] = "assistant"
                ctx["started"] = True

            text = "".join(
                str(part.get("text", ""))
                for part in parts
                if isinstance(part, dict) and "text" in part
            )
            if text:
                delta["content"] = text

            tool_calls: List[Dict[str, Any]] = []
            for part in parts:
                if not isinstance(part, dict):
                    continue
                function_call = part.get("functionCall")
                if not function_call:
                    continue
                # Gemini delivers a complete ``functionCall`` per part (OpenAI
                # streams ``arguments`` in fragments), so one part is one new
                # accumulated call — the index has to keep counting across
                # chunks, otherwise calls arriving in separate chunks collapse
                # into a single tool call on the client side.
                tool_call: Dict[str, Any] = {
                    "index": ctx["tool_seq"],
                    "id": f"vertex_fc_{ctx['tool_seq']}",
                    "type": "function",
                    "function": {
                        "name": function_call.get("name", ""),
                        "arguments": json.dumps(function_call.get("args") or {}),
                    },
                }
                _carry_thought_signature(part, tool_call)
                tool_calls.append(tool_call)
                ctx["tool_seq"] += 1
                ctx["tool_call_seen"] = True
            if tool_calls:
                delta["tool_calls"] = tool_calls

            finish = candidate.get("finishReason")
            finish_reason = (
                VertexAiConverters.map_finish_reason(
                    finish, bool(ctx.get("tool_call_seen"))
                )
                if finish
                else None
            )

            out: Dict[str, Any] = {
                "id": ctx["id"],
                "object": "chat.completion.chunk",
                "created": ctx["created"],
                "model": ctx["model"],
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }
            if chunk.get("usageMetadata"):
                out["usage"] = cls._usage(chunk.get("usageMetadata"))
            return out

        @staticmethod
        def convert_embedding(response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert a Vertex ``batchEmbedContents`` response to the OpenAI
            embeddings list schema.
            """
            embeddings = response.get("embeddings") or []
            data = [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": (
                        item.get("values", []) if isinstance(item, dict) else []
                    ),
                }
                for index, item in enumerate(embeddings)
            ]
            total_tokens = int(
                (response.get("usageMetadata") or {}).get("totalTokenCount") or 0
            )
            return {
                "object": "list",
                "data": data,
                "model": response.get("model", ""),
                "usage": {
                    "prompt_tokens": total_tokens,
                    "total_tokens": total_tokens,
                },
            }
