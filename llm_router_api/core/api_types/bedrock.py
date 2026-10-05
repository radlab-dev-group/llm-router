"""
Amazon Bedrock API integration utilities.

The module provides two main utilities for working with Bedrock in the
*llm‑router* code‑base:

1. **BedrockType** – a concrete implementation of
   :class:`llm_router_api.core.api_types.types_i.ApiTypesI`.  Bedrock addresses
   the model in the URL (``/model/{modelId}/converse``) and authenticates with
   SigV4 rather than a bearer token, so the type overrides the request adapter
   hooks to build the operation path, the native Converse bodies and — uniquely
   among the router's provider types — the request *signature*.

2. **BedrockConverters** – a namespace grouping the conversion helpers between
   the OpenAI wire format (what the router's public endpoints speak) and the
   Bedrock Converse wire format: request payloads, chat responses, stream events
   and embeddings.

Chat and streaming use the **Converse API**, whose request/response shape is
uniform across every messaging model on Bedrock, so one translator covers
Anthropic, Meta, Mistral, AI21 and the rest.  Embeddings have no Converse
equivalent and go through ``InvokeModel`` with a per-model family body.

``boto3`` is optional (only the credential chain needs it, see
:mod:`llm_router_api.core.api_types.auth.aws`); signing, framing and conversion
are pure standard library.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from llm_router_api.core.api_types.auth.aws import (
    AwsCredentialProvider,
    AwsSigV4Signer,
)
from llm_router_api.core.api_types.types_i import ApiTypesI

logger = logging.getLogger(__name__)

#: Path fragments of the Bedrock runtime API.
CONVERSE_OPERATION = "converse"
STREAM_CONVERSE_OPERATION = "converse-stream"
INVOKE_OPERATION = "invoke"

#: Host template of the region specific runtime endpoint.
RUNTIME_HOST_TEMPLATE = "https://bedrock-runtime.{region}.amazonaws.com"

#: Image formats the Converse API accepts (lowercase suffix without the dot).
_SUPPORTED_IMAGE_FORMATS = frozenset({"jpeg", "png", "gif", "webp"})

#: Bedrock ``stopReason`` → OpenAI ``finish_reason``.
_FINISH_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "tool_use": "tool_calls",
    "content_filtered": "content_filter",
    "guardrail_intervened": "content_filter",
}


class BedrockType(ApiTypesI):
    """
    Concrete descriptor for Amazon Bedrock endpoints.

    The wire protocol is not OpenAI‑compatible: the model lives in the URL, the
    body is a Converse request (``messages`` / ``system`` / ``inferenceConfig``
    / ``toolConfig``), streaming is a binary event stream, and authentication is
    a SigV4 signature over the transmitted body rather than a bearer token.
    """

    # ------------------------------------------------------------------
    # Endpoint descriptors
    # ------------------------------------------------------------------
    def chat_ep(self) -> str:
        """
        Return the Converse operation suffix.
        """
        return CONVERSE_OPERATION

    def completions_ep(self) -> str:
        """
        Bedrock serves completions through the Converse operation.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """
        Bedrock serves responses through the Converse operation.
        """
        return self.chat_ep()

    def embeddings_ep(self) -> str:
        """
        Embeddings have no Converse operation and use ``invoke``.
        """
        return INVOKE_OPERATION

    # ------------------------------------------------------------------
    # Provider helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _provider_options(provider: Any) -> Dict[str, Any]:
        """
        Return the provider's ``provider_options`` mapping (empty when absent).
        """
        options = ApiTypesI._provider_field(provider, "provider_options", None)
        return dict(options) if isinstance(options, dict) else {}

    @staticmethod
    def _model_id(provider: Any) -> str:
        """
        Return the Bedrock model identifier.

        A base model ID (``anthropic.claude-…-v1:0``), a cross-region inference
        profile (``eu.anthropic.claude-…``) and a model ARN are all accepted
        verbatim: the API takes any of them in the ``modelId`` path segment, and
        re-encoding one would change the resource it names.
        """
        model = str(
            ApiTypesI._provider_field(provider, "model_path", "")
            or ApiTypesI._provider_field(provider, "name", "")
            or ""
        ).strip()
        return model.lstrip("/")

    @classmethod
    def region(cls, provider: Any) -> str:
        """
        Resolve the AWS region used for both signing and host derivation.
        """
        return AwsCredentialProvider.resolve_region(cls._provider_options(provider))

    def _request_path(self, provider: Any, operation: str) -> str:
        """
        Build ``/model/{modelId}/{operation}``.
        """
        return f"/model/{self._model_id(provider)}/{operation}"

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
        Build the Bedrock operation path for the requested endpoint.
        """
        fragment = (endpoint_url or "").strip("/")
        if "embed" in fragment:
            operation = self.embeddings_ep()
        elif stream:
            operation = STREAM_CONVERSE_OPERATION
        else:
            operation = CONVERSE_OPERATION
        return self._request_path(provider, operation)

    def request_headers(self, provider: Any) -> Dict[str, str]:
        """
        Build the outbound headers for ``provider``.

        A Bedrock API key authenticates as a plain bearer token and is complete
        here.  IAM credentials are *not*: a SigV4 signature covers the request
        body, which this hook cannot see, so the headers stay unsigned and
        :meth:`sign_request` finishes them once the body is serialised.
        """
        headers = super().request_headers(provider)
        headers.pop("Authorization", None)
        token = str(self._provider_field(provider, "api_token", "") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def signs_payload(self) -> bool:
        """
        Bedrock signs the request body (SigV4), so the transport must hand the
        signature the exact bytes it will transmit.
        """
        return True

    def sign_request(
        self,
        provider: Any,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes],
    ) -> Dict[str, str]:
        """
        Sign the assembled request with SigV4.

        Providers carrying a Bedrock API key (``api_token``) are already
        authenticated by :meth:`request_headers` and pass through untouched.
        """
        if str(self._provider_field(provider, "api_token", "") or "").strip():
            return headers
        options = self._provider_options(provider)
        region = AwsCredentialProvider.resolve_region(options)
        credentials = AwsCredentialProvider.get_credentials(options)
        return AwsSigV4Signer.sign(
            method=method,
            url=url,
            headers=headers,
            body=body,
            region=region,
            credentials=credentials,
        )

    def request_body(
        self,
        payload: Any,
        provider: Any,
        system_message: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Translate an OpenAI‑style payload into a Bedrock request body.
        """
        params = dict(payload or {})
        params.pop("stream", None)
        # Embeddings endpoints speak OpenAI (``input``), chat endpoints speak
        # ``messages``; the two never coexist in one payload.
        if "input" in params and "messages" not in params:
            return self._build_embedding_body(params, provider)
        if system_message:
            messages = list(params.get("messages") or [])
            messages.insert(0, dict(system_message))
            params["messages"] = messages
        return BedrockConverters.Payload.convert_payload(params, provider=provider)

    def owns_message_normalization(self) -> bool:
        """
        The Converse translator merges same‑role turns itself (keeping
        ``tool_call_id`` information), so the router's normaliser must not run
        first.
        """
        return True

    def ping_path(self, provider: Any) -> Optional[str]:
        """
        No health‑check path.

        The Bedrock runtime offers no cheap ``GET``: ``converse`` is POST‑only,
        and a probe that actually invoked a model would cost tokens on every
        monitor cycle.  Returning ``None`` hands the decision to the monitor's
        generic probe list rather than inventing an endpoint that answers 404.
        """
        return None

    def on_response_status(self, provider: Any, status_code: int) -> None:
        """
        Evict chain‑resolved AWS credentials the upstream rejected.

        A ``401``/``403`` signed with credentials from the boto3 chain means the
        material went stale (rotated key, expired role session); without the
        eviction every later request replays the same rejected credentials.
        Credentials the operator manages directly (``api_token``, inline
        ``access_key_id``) are left alone — the router's cache holds nothing to
        drop.
        """
        if status_code not in (401, 403):
            return
        if str(self._provider_field(provider, "api_token", "") or "").strip():
            return
        options = self._provider_options(provider)
        if str(options.get("access_key_id") or "").strip():
            return
        if AwsCredentialProvider._from_environment() is not None:
            # Static environment keys are never in the cache; nothing to evict.
            return
        AwsCredentialProvider.invalidate(options)

    # ------------------------------------------------------------------
    # Embeddings (InvokeModel)
    # ------------------------------------------------------------------
    def _build_embedding_body(
        self, params: Dict[str, Any], provider: Any
    ) -> Dict[str, Any]:
        """
        Translate an OpenAI embeddings payload into an ``InvokeModel`` body.

        Unlike Converse, the embedding body is model specific; the family is
        inferred from the model ID and ``provider_options.embedding_body``
        overrides the whole document for anything unrecognised.
        """
        return BedrockConverters.Payload.build_embedding_body(
            params, provider=provider, model_id=self._model_id(provider)
        )


class BedrockConverters:
    """
    Namespace for payload‑conversion utilities for Amazon Bedrock.

    Nested classes:

    * ``Payload`` – OpenAI request → Converse body / ``invoke`` embedding body;
    * ``FromBedrock`` – Bedrock responses → OpenAI chat / stream / embeddings.
    """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    @classmethod
    def map_finish_reason(
        cls, stop_reason: Any, has_tool_calls: bool = False
    ) -> str:
        """
        Translate a Bedrock ``stopReason`` into the OpenAI ``finish_reason``.

        Unknown values collapse to ``"stop"`` rather than ``None``: a terminal
        chunk without a finish reason leaves OpenAI clients waiting for an end
        that never arrives.
        """
        if has_tool_calls:
            return "tool_calls"
        mapped = _FINISH_REASON_MAP.get(str(stop_reason or ""))
        return mapped or "stop"

    @staticmethod
    def is_bedrock_converse_response(payload: Dict[str, Any]) -> bool:
        """
        True when *payload* looks like a Converse response.

        Deliberately narrow: ``output.message`` is nested, so the Converse body
        does not collide with the Ollama (top‑level ``message``) or Anthropic
        (``content`` + ``role`` + ``id``) sniffing it sits next to.
        """
        if not isinstance(payload, dict):
            return False
        if "stopReason" in payload:
            return True
        output = payload.get("output")
        return isinstance(output, dict) and "message" in output

    @staticmethod
    def is_bedrock_embedding_response(payload: Dict[str, Any]) -> bool:
        """
        True when *payload* looks like a Bedrock ``invoke`` embedding response.

        Titan answers with a singular ``embedding``, Nova nests it under
        ``output``, Cohere adds ``response_type: "embeddings"`` — all distinct
        from the OpenAI ``data`` list and from the Ollama ``embeddings`` list of
        vectors, which would otherwise swallow the Cohere shape.
        """
        if not isinstance(payload, dict):
            return False
        if "inputTextTokenCount" in payload or "embedding" in payload:
            return True
        if payload.get("response_type") == "embeddings":
            return True
        output = payload.get("output")
        return isinstance(output, dict) and "embedding" in output

    @staticmethod
    def _image_from_url(url: str) -> Optional[Dict[str, Any]]:
        """
        Convert an OpenAI ``image_url`` into a Converse ``image`` block.

        ``source.bytes`` is a JSON blob, i.e. base64 text — which is exactly
        what a ``data:`` URL already carries, so it is passed through unchanged.
        A remote ``http(s)`` URL has no Converse equivalent (Bedrock does not
        fetch URLs) and is reported rather than silently dropped.
        """
        if not url:
            return None
        if not url.startswith("data:"):
            logger.warning(
                "Bedrock cannot fetch a remote image URL; skipping %r. Pass the "
                "image as a base64 data: URL or pre-upload it to S3.",
                url[:80],
            )
            return None
        header, _, encoded = url.partition(",")
        mime = header[5:].split(";")[0].lower()
        fmt = mime.rsplit("/", 1)[-1]
        if fmt == "jpg":
            fmt = "jpeg"
        if fmt not in _SUPPORTED_IMAGE_FORMATS:
            logger.warning("Unsupported image format %r for Bedrock; skipping.", fmt)
            return None
        try:
            base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            logger.warning("Image data URL is not valid base64; skipping.")
            return None
        return {"format": fmt, "source": {"bytes": encoded}}

    @staticmethod
    def _message_content_blocks(content: Any) -> List[Dict[str, Any]]:
        """
        Convert an OpenAI message ``content`` (string or parts list) into
        Converse content blocks.
        """
        if content is None or content == "":
            return [{"text": ""}]
        if isinstance(content, str):
            return [{"text": content}]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        blocks: List[Dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                blocks.append({"text": item})
                continue
            if not isinstance(item, dict):
                logger.debug("Skipping non-dict content part: %r", item)
                continue
            item_type = item.get("type")
            if item_type is None and "text" in item:
                item_type = "text"
            if item_type == "text":
                blocks.append({"text": str(item.get("text", ""))})
            elif item_type == "image_url":
                image = BedrockConverters._image_from_url(
                    (item.get("image_url") or {}).get("url") or ""
                )
                if image:
                    blocks.append({"image": image})
            else:
                logger.debug("Skipping unsupported content part: %r", item_type)
        return blocks or [{"text": ""}]

    @staticmethod
    def _parse_tool_input(raw: Any, name: str = "") -> Dict[str, Any]:
        """
        Translate an OpenAI ``arguments`` value into a Converse ``input`` object.

        Converse wants a JSON *object* here (OpenAI sends a string).  Nothing
        unusable is invented: a fabricated key would not match the submitted
        ``toolSpec`` and a placeholder name would turn a salvageable request into
        a hard ``400``, so anything unparseable degrades to ``{}`` with a warning.
        """
        if isinstance(raw, dict):
            return dict(raw)
        if raw is None or raw == "":
            return {}
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        logger.warning(
            "Could not parse arguments of tool %r as a JSON object; sending "
            "empty input instead.",
            name or "unknown",
        )
        return {}

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
                name = function.get("name") if isinstance(function, dict) else None
                if call_id and name:
                    names[call_id] = str(name)
        return names

    # ------------------------------------------------------------------
    # Request payload
    # ------------------------------------------------------------------
    class Payload:
        """
        Converters from OpenAI request format to Bedrock format.
        """

        @classmethod
        def convert_payload(
            cls,
            params: Dict[str, Any],
            provider: Any = None,
        ) -> Dict[str, Any]:
            """
            Convert an OpenAI chat payload to a Converse request body.

            Converse requires strictly alternating ``user`` / ``assistant``
            turns, so consecutive messages of the same mapped role are merged
            into one message — keeping the ``toolResult`` blocks that a
            router-level normaliser would lose.
            """
            params = dict(params or {})
            messages = params.get("messages") or []
            tool_names = cls._tool_names(messages)

            converted: List[Dict[str, Any]] = []
            system_blocks: List[Dict[str, Any]] = []
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "user").lower()
                if role == "system":
                    system_blocks.extend(
                        BedrockConverters._message_content_blocks(
                            message.get("content")
                        )
                    )
                    continue
                if role == "tool":
                    block = cls._tool_result_block(message, tool_names)
                    if block is None:
                        continue
                    blocks, bedrock_role = [block], "user"
                elif role in ("assistant", "model"):
                    blocks = cls._assistant_blocks(message)
                    bedrock_role = "assistant"
                else:
                    blocks = BedrockConverters._message_content_blocks(
                        message.get("content")
                    )
                    bedrock_role = "user"
                if not blocks:
                    continue
                if converted and converted[-1]["role"] == bedrock_role:
                    converted[-1]["content"].extend(blocks)
                else:
                    converted.append({"role": bedrock_role, "content": blocks})

            body: Dict[str, Any] = {"messages": converted}
            if system_blocks:
                body["system"] = system_blocks

            inference_config = cls._inference_config(params)
            if inference_config:
                body["inferenceConfig"] = inference_config

            tool_config = cls._tool_config(params)
            if tool_config:
                body["toolConfig"] = tool_config

            output_config = cls._output_config(params)
            if output_config:
                body["outputConfig"] = output_config

            options = (
                BedrockType._provider_options(provider)
                if provider is not None
                else {}
            )
            additional = options.get("additional_model_request_fields")
            if isinstance(additional, dict) and additional:
                body["additionalModelRequestFields"] = additional
            guardrail = options.get("guardrail_config")
            if isinstance(guardrail, dict) and guardrail:
                body["guardrailConfig"] = guardrail
            return body

        @staticmethod
        def _tool_names(messages: List[Any]) -> Dict[str, str]:
            return BedrockConverters._tool_call_names(messages)

        @classmethod
        def _assistant_blocks(cls, message: Dict[str, Any]) -> List[Dict[str, Any]]:
            """
            Build one assistant message: its text, then its tool uses.

            A pure tool-call turn yields the ``toolUse`` blocks only — an empty
            ``{"text": ""}`` next to a tool use is rejected by some models.
            """
            content = message.get("content")
            blocks: List[Dict[str, Any]] = []
            if content not in (None, "", []):
                blocks.extend(BedrockConverters._message_content_blocks(content))
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict) or not function.get("name"):
                    continue
                blocks.append(
                    {
                        "toolUse": {
                            "toolUseId": str(
                                tool_call.get("id")
                                or f"tooluse_{uuid.uuid4().hex[:21]}"
                            ),
                            "name": str(function["name"]),
                            "input": BedrockConverters._parse_tool_input(
                                function.get("arguments"), str(function["name"])
                            ),
                        }
                    }
                )
            return blocks or [{"text": ""}]

        @staticmethod
        def _tool_result_block(
            message: Dict[str, Any], names: Dict[str, str]
        ) -> Optional[Dict[str, Any]]:
            """
            Convert an OpenAI ``role: tool`` message into a ``toolResult``.

            ``toolUseId`` is mandatory and must name an earlier ``toolUse``, so
            a message whose call cannot be identified is dropped with a warning
            instead of being sent with a placeholder.
            """
            call_id = str(message.get("tool_call_id") or "")
            if not call_id:
                logger.warning(
                    "Dropping tool message without tool_call_id: Bedrock "
                    "requires toolResult.toolUseId to match a previous toolUse."
                )
                return None
            name = str(message.get("name") or names.get(call_id) or "")
            content = message.get("content")
            if isinstance(content, list):
                result_blocks = [
                    block
                    for block in BedrockConverters._message_content_blocks(content)
                    if "text" in block
                ] or [{"text": ""}]
            else:
                result_blocks = [{"text": "" if content is None else str(content)}]
            block: Dict[str, Any] = {
                "toolResult": {"toolUseId": call_id, "content": result_blocks}
            }
            if name:
                block["toolResult"]["name"] = name
            return block

        @staticmethod
        def _inference_config(params: Dict[str, Any]) -> Dict[str, Any]:
            """
            Build ``inferenceConfig`` from the OpenAI sampling parameters.
            """
            config: Dict[str, Any] = {}
            if params.get("temperature") is not None:
                config["temperature"] = params["temperature"]
            if params.get("top_p") is not None:
                config["topP"] = params["top_p"]

            max_tokens = params.get(
                "max_tokens", params.get("max_completion_tokens")
            )
            if max_tokens is not None:
                try:
                    max_tokens = int(max_tokens)
                except (TypeError, ValueError):
                    max_tokens = None
                if max_tokens and max_tokens > 0:
                    config["maxTokens"] = max_tokens

            stop = params.get("stop")
            if stop:
                config["stopSequences"] = stop if isinstance(stop, list) else [stop]
            return config

        @staticmethod
        def _tool_config(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """
            Build ``toolConfig`` (``tools`` + ``toolChoice``) from OpenAI fields.
            """
            config: Dict[str, Any] = {}
            tools: List[Dict[str, Any]] = []
            for tool in params.get("tools") or []:
                if not isinstance(tool, dict):
                    continue
                if tool.get("type") not in (None, "function"):
                    continue
                function = tool.get("function")
                if not isinstance(function, dict) or not function.get("name"):
                    continue
                spec: Dict[str, Any] = {"name": str(function["name"])}
                if function.get("description"):
                    spec["description"] = function["description"]
                # Converse wraps the schema in an ``inputSchema`` union; only the
                # ``json`` member is representable.
                spec["inputSchema"] = {"json": function.get("parameters") or {}}
                tools.append({"toolSpec": spec})
            if tools:
                config["tools"] = tools

            choice = params.get("tool_choice")
            if isinstance(choice, str):
                mapped = {"auto": "auto", "none": "none", "required": "any"}.get(
                    choice
                )
                if mapped:
                    config["toolChoice"] = {mapped: {}}
            elif isinstance(choice, dict) and choice.get("type") == "function":
                name = (choice.get("function") or {}).get("name")
                if name:
                    config["toolChoice"] = {"tool": {"name": str(name)}}
            return config or None

        @staticmethod
        def _output_config(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            """
            Map OpenAI ``response_format`` onto Converse ``outputConfig``.

            ``json_object`` becomes a plain JSON text type; ``json_schema``
            carries its schema through ``textFormat.structure``.
            """
            response_format = params.get("response_format")
            if not isinstance(response_format, dict):
                return None
            kind = response_format.get("type")
            if kind == "json_object":
                return {"textFormat": {"type": "json"}}
            if kind == "json_schema":
                schema = (response_format.get("json_schema") or {}).get("schema")
                text_format: Dict[str, Any] = {"type": "json"}
                if schema:
                    text_format["structure"] = {"json": schema}
                return {"textFormat": text_format}
            return None

        # ------------------------------------------------------------------
        # Embeddings (InvokeModel, per model family)
        # ------------------------------------------------------------------
        @staticmethod
        def embedding_family(model_id: str) -> str:
            """
            Classify an embedding model ID into its request body family.

            Returns one of ``titan_v1`` / ``titan`` / ``nova`` / ``cohere_v3`` /
            ``cohere_v4``; anything else is ``unknown``.  Region segments are
            dropped first: AWS spells a regional inference profile both as a
            leading segment (``eu.anthropic.…``) and, for Cohere, after the
            vendor (``cohere.eu.embed-…``).
            """
            identifier = str(model_id or "").lower()
            identifier = ".".join(
                segment
                for segment in identifier.split(".")
                if segment not in ("eu", "apac", "us", "global")
            )
            # Drop a trailing ":0" style version marker before matching, so
            # "…-v1:0" and "…-v1" classify alike.
            base = identifier.split(":")[0]

            if "nova-embed" in base:
                return "nova"
            if base.startswith("cohere.embed"):
                return "cohere_v4" if base.endswith("-v4") else "cohere_v3"
            if base.startswith("amazon.titan-embed") or base.startswith(
                "titan-embed"
            ):
                return "titan_v1" if base.endswith("-v1") else "titan"
            return "unknown"

        @classmethod
        def build_embedding_body(
            cls,
            params: Dict[str, Any],
            provider: Any = None,
            model_id: str = "",
        ) -> Dict[str, Any]:
            """
            Build the ``invoke`` body for one embedding model family.

            An unknown model raises rather than guessing a body: a wrong shape
            is a confusing ``400`` from Bedrock, while this message names the
            override that works.
            """
            inputs = params.get("input")
            if isinstance(inputs, str):
                inputs = [inputs]
            if not isinstance(inputs, list):
                inputs = [str(inputs)]
            texts = [str(text) for text in inputs]

            options = (
                BedrockType._provider_options(provider)
                if provider is not None
                else {}
            )
            override = options.get("embedding_body")
            if isinstance(override, dict) and override:
                # Operator-supplied template; ``{input}`` placeholders are not
                # interpreted — supply a static document or use a family we know.
                body = dict(override)
                if len(texts) == 1:
                    body.setdefault("inputText", texts[0])
                return body

            identifier = model_id or str(
                ApiTypesI._provider_field(provider, "model_path", "")
                or ApiTypesI._provider_field(provider, "name", "")
                or ""
            )
            family = cls.embedding_family(identifier)

            dimensions: Optional[int] = None
            raw_dimensions = params.get("dimensions")
            if raw_dimensions is not None:
                try:
                    dimensions = int(raw_dimensions)
                except (TypeError, ValueError):
                    dimensions = None

            if family in ("titan", "titan_v1"):
                if len(texts) > 1:
                    raise ValueError(
                        f"Bedrock embedding model {identifier!r} accepts one "
                        "input per request; send a single string or use a model "
                        "that supports batches."
                    )
                body: Dict[str, Any] = {"inputText": texts[0]}
                if dimensions and family == "titan":
                    body["dimensions"] = dimensions
                return body
            if family == "nova":
                if len(texts) > 1:
                    raise ValueError(
                        f"Bedrock embedding model {identifier!r} accepts one "
                        "input per request."
                    )
                body = {"input": {"text": texts[0]}}
                if dimensions:
                    body["config"] = {"dimensions": dimensions}
                return body
            if family == "cohere_v3":
                body = {
                    "texts": texts,
                    "input_type": str(
                        options.get("embedding_input_type") or "search_document"
                    ),
                }
                if options.get("embedding_truncate"):
                    body["truncate"] = str(options["embedding_truncate"])
                return body
            if family == "cohere_v4":
                return {
                    "texts": texts,
                    "input_type": str(
                        options.get("embedding_input_type") or "input"
                    ),
                    "embedding_types": ["float"],
                }
            raise ValueError(
                f"Unsupported Bedrock embedding model {identifier!r}. Supported "
                "families: amazon.titan-embed-*, amazon.nova-embed-*, "
                "cohere.embed-*. For another model, set the exact request "
                "document in provider_options.embedding_body."
            )

    # ------------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------------
    class FromBedrock:
        """
        Converters from Bedrock response format to OpenAI format.
        """

        @staticmethod
        def _usage(usage: Any) -> Dict[str, Any]:
            data = usage if isinstance(usage, dict) else {}
            prompt_tokens = int(data.get("inputTokens") or 0)
            completion_tokens = int(data.get("outputTokens") or 0)
            total = int(data.get("totalTokens") or prompt_tokens + completion_tokens)
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total,
                "prompt_tokens_details": None,
                "completion_tokens_details": {"reasoning_tokens": 0},
            }

        @staticmethod
        def _blocks_text(content: Any) -> str:
            return "".join(
                str(block.get("text", ""))
                for block in (content or [])
                if isinstance(block, dict) and "text" in block
            )

        @staticmethod
        def _tool_uses(
            content: Any, id_prefix: str = "bedrock"
        ) -> List[Dict[str, Any]]:
            tool_calls: List[Dict[str, Any]] = []
            for block in content or []:
                if not isinstance(block, dict):
                    continue
                tool_use = block.get("toolUse")
                if not tool_use:
                    continue
                tool_calls.append(
                    {
                        "id": str(
                            tool_use.get("toolUseId")
                            or f"{id_prefix}_fc_{len(tool_calls)}"
                        ),
                        "type": "function",
                        "function": {
                            "name": tool_use.get("name", ""),
                            "arguments": json.dumps(tool_use.get("input") or {}),
                        },
                    }
                )
            return tool_calls

        @classmethod
        def convert_response(cls, response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert a Converse response to the OpenAI Chat Completion schema.
            """
            response = response or {}
            output = response.get("output") or {}
            message = output.get("message") or {}
            content = message.get("content") or []

            tool_calls = cls._tool_uses(content)
            finish_reason = BedrockConverters.map_finish_reason(
                response.get("stopReason"), bool(tool_calls)
            )

            return {
                "id": f"bedrock-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": str(response.get("modelInvokedArn") or ""),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": cls._blocks_text(content),
                            "refusal": None,
                            "annotations": None,
                            "audio": None,
                            "function_call": None,
                            "tool_calls": tool_calls,
                            "reasoning_content": None,
                        },
                        "logprobs": None,
                        "finish_reason": finish_reason,
                        "stop_reason": None,
                        "token_ids": None,
                    }
                ],
                "service_tier": None,
                "system_fingerprint": None,
                "usage": cls._usage(response.get("usage")),
                "prompt_logprobs": None,
                "prompt_token_ids": None,
                "kv_transfer_params": None,
            }

        @staticmethod
        def new_stream_ctx(model: str = "") -> Dict[str, Any]:
            """
            Build the per‑stream conversion context.

            ``tools`` tracks the in‑flight tool uses by ``contentBlockIndex``:
            Converse opens a block with the tool's id and name, then streams the
            ``input`` as JSON *fragments* that must be reassembled per block.
            """
            return {
                "id": f"chatcmpl-bedrock-{uuid.uuid4().hex[:24]}",
                "created": int(time.time()),
                "model": model or "",
                "started": False,
                "tools": {},
                "tool_seq": 0,
                "tool_call_seen": False,
                "finish_reason": None,
                "usage": None,
            }

        @classmethod
        def new_final_chunk(
            cls, ctx: Dict[str, Any], finish_reason: str = "stop"
        ) -> Dict[str, Any]:
            """
            Build the terminal ``chat.completion.chunk`` of a converted stream.
            """
            chunk = {
                "id": ctx["id"],
                "object": "chat.completion.chunk",
                "created": ctx["created"],
                "model": ctx["model"],
                "choices": [
                    {"index": 0, "delta": {}, "finish_reason": finish_reason}
                ],
            }
            if ctx.get("usage"):
                chunk["usage"] = ctx["usage"]
            return chunk

        @classmethod
        def convert_event(
            cls, event_type: str, payload: Dict[str, Any], ctx: Dict[str, Any]
        ) -> Optional[Dict[str, Any]]:
            """
            Convert one decoded Bedrock stream event into an OpenAI chunk.

            Returns ``None`` when the event carries nothing an OpenAI client
            consumes (``messageStart``, ``contentBlockStop``), and defers the
            terminal chunk to :meth:`flush` so a ``messageStop`` that arrives
            without a preceding delta is still well formed.
            """
            payload = payload or {}

            if event_type == "contentBlockDelta":
                delta = payload.get("delta") or {}
                out_delta: Dict[str, Any] = {}
                if not ctx["started"]:
                    out_delta["role"] = "assistant"
                    ctx["started"] = True

                text = delta.get("text")
                if text:
                    out_delta["content"] = str(text)

                tool_delta = delta.get("toolUse")
                tool_calls: List[Dict[str, Any]] = []
                if tool_delta:
                    index = int(payload.get("contentBlockIndex") or 0)
                    tracked = ctx["tools"].setdefault(
                        index, {"seq": ctx["tool_seq"], "name": None}
                    )
                    if tracked["seq"] == ctx["tool_seq"]:
                        # First fragment of a new block: it owns the next index.
                        ctx["tool_seq"] += 1
                    ctx["tool_call_seen"] = True
                    call: Dict[str, Any] = {
                        "index": tracked["seq"],
                        "type": "function",
                        "function": {},
                    }
                    input_fragment = (tool_delta or {}).get("input")
                    if isinstance(input_fragment, dict):
                        # Some models deliver the whole object in one event.
                        call["function"]["arguments"] = json.dumps(input_fragment)
                    elif input_fragment:
                        call["function"]["arguments"] = str(input_fragment)
                    tool_calls.append(call)
                    out_delta["tool_calls"] = tool_calls

                if not out_delta:
                    return None
                return cls._chunk(ctx, out_delta)

            if event_type == "contentBlockStart":
                start = payload.get("start") or {}
                tool_use = start.get("toolUse")
                if not tool_use:
                    return None
                index = int(payload.get("contentBlockIndex") or 0)
                tracked = ctx["tools"].setdefault(
                    index, {"seq": ctx["tool_seq"], "name": None}
                )
                if tracked["seq"] == ctx["tool_seq"]:
                    ctx["tool_seq"] += 1
                ctx["tool_call_seen"] = True
                out_delta = {
                    "tool_calls": [
                        {
                            "index": tracked["seq"],
                            "id": str(
                                tool_use.get("toolUseId")
                                or f"bedrock_fc_{tracked['seq']}"
                            ),
                            "type": "function",
                            "function": {
                                "name": str(tool_use.get("name") or ""),
                                "arguments": "",
                            },
                        }
                    ]
                }
                if not ctx["started"]:
                    out_delta["role"] = "assistant"
                    ctx["started"] = True
                return cls._chunk(ctx, out_delta)

            if event_type == "messageStop":
                ctx["finish_reason"] = BedrockConverters.map_finish_reason(
                    payload.get("stopReason"), bool(ctx.get("tool_call_seen"))
                )
                return None

            if event_type == "metadata":
                usage = payload.get("usage")
                if usage:
                    ctx["usage"] = cls._usage(usage)
                invoked = (
                    payload.get("trace", {})
                    .get("promptRouter", {})
                    .get("invokedModelId")
                )
                if invoked:
                    ctx["model"] = str(invoked)
                return None

            # messageStart, contentBlockStop and any future event we do not map.
            logger.debug("Ignoring Bedrock stream event %r", event_type)
            return None

        @staticmethod
        def _chunk(ctx: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "id": ctx["id"],
                "object": "chat.completion.chunk",
                "created": ctx["created"],
                "model": ctx["model"],
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
            }

        @classmethod
        def flush(cls, ctx: Dict[str, Any]) -> Dict[str, Any]:
            """
            Build the terminal chunk, honouring the reason Bedrock reported.
            """
            return cls.new_final_chunk(
                ctx,
                ctx.get("finish_reason")
                or BedrockConverters.map_finish_reason(
                    None, bool(ctx.get("tool_call_seen"))
                ),
            )

        @classmethod
        def convert_embedding(cls, response: Dict[str, Any]) -> Dict[str, Any]:
            """
            Convert a Bedrock embedding response to the OpenAI embeddings schema.

            Handles the three shapes in the wild: Titan's singular
            ``embedding``, Nova's ``output.embedding`` and Cohere's
            ``embeddings`` list (v3) or ``embeddings.float`` (v4).
            """
            response = response or {}
            vectors: List[Any] = []
            total_tokens = 0

            if "embedding" in response and isinstance(
                response.get("embedding"), list
            ):
                # Titan v1/v2: one vector per request.
                vectors = [response["embedding"]]
                total_tokens = int(response.get("inputTextTokenCount") or 0)
            elif isinstance(response.get("output"), dict):
                output = response["output"]
                # Nova returns a single **flat** vector, unlike Cohere's list of
                # vectors, so it has to be wrapped to line up with ``index``.
                embedding = output.get("embedding") or []
                vectors = [embedding] if embedding else []
                usage = response.get("usage") or {}
                total_tokens = int(usage.get("inputTokens") or 0)
            else:
                embeddings = response.get("embeddings")
                if isinstance(embeddings, dict):
                    # Cohere v4 groups vectors by representation.
                    vectors = list(embeddings.get("float") or [])
                elif isinstance(embeddings, list):
                    vectors = list(embeddings)
                usage = response.get("usage") or {}
                if isinstance(usage, dict):
                    total_tokens = int(
                        usage.get("total_tokens")
                        or usage.get("texts_tokens")
                        or usage.get("input_tokens")
                        or 0
                    )

            data = [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": vector if isinstance(vector, list) else [],
                }
                for index, vector in enumerate(vectors)
            ]
            return {
                "object": "list",
                "data": data,
                "model": str(response.get("model") or ""),
                "usage": {
                    "prompt_tokens": total_tokens,
                    "total_tokens": total_tokens,
                },
            }
