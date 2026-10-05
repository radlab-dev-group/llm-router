"""
Utilities for handling streaming HTTP responses.

The original functional helpers have been wrapped inside the
`StreamHandler` class.  This makes the behavior easier to inject
(e.g. a mock stream handler in tests) and groups related logic
together.
"""

import json
import datetime
import requests
import contextlib

from enum import Enum, auto
from requests import Response
from typing import Iterator, Dict, Any, Optional

from llm_router_api.base.constants_base import OPENAI_COMPATIBLE_PROVIDERS
from llm_router_api.core.api_types.bedrock import BedrockConverters
from llm_router_api.core.api_types.dispatcher import ApiTypesDispatcher
from llm_router_api.core.api_types.eventstream import (
    AwsEventStreamError,
    iter_events,
)
from llm_router_api.core.api_types.vertex_ai import VertexAiConverters
from llm_router_api.core.errors import (
    ProviderStreamError,
    connection_error_code,
    sanitize_error_message,
)


def _request_error_message(exc: Exception) -> str:
    """
    Build a human‑readable error string for a failed provider request.

    Unlike ``str(HTTPError)`` (which only carries the status line), this
    also surfaces the provider's response body — e.g. Google's
    ``400 {"error": {"message": "Invalid value for parameter ..."}}`` —
    truncated to 500 characters so the client/operator can see *why*
    the provider rejected the request.
    """
    base = sanitize_error_message(str(exc))
    body = getattr(exc, "provider_body", None)
    if not body:
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                body = (resp.text or "").strip()
            except Exception:
                body = ""
    if not body:
        return base
    return f"{base} — provider: {body[:500]}"


def _raise_for_status(resp: Response) -> None:
    """
    Raise a :class:`ProviderStreamError` for a non‑2xx response **while the
    response is still open**, capturing the provider's body for the message.

    Plain ``resp.raise_for_status()`` does not work here: it is called
    inside ``with resp:`` blocks, so by the time the surrounding
    ``except`` handler runs the response is already closed and its body
    can no longer be read.

    The failure happens before any chunk was produced, so the dispatcher can
    still retry the request on another provider; the dedicated exception type
    (instead of ``requests.HTTPError``) keeps the per‑format generators from
    turning it into a final error chunk.
    """
    if resp is None or resp.status_code < 400:
        return
    try:
        body = (resp.text or "").strip()
    except Exception:
        body = ""
    exc = requests.HTTPError(
        f"{resp.status_code} {getattr(resp, 'reason', '')} for url: {resp.url}",
        response=resp,
    )
    exc.provider_body = body[:1000]  # type: ignore[attr-defined]
    raise ProviderStreamError(
        status_code=resp.status_code,
        message=_request_error_message(exc),
        provider_body=body[:1000],
    ) from exc


def _pre_content_failure(exc: Exception) -> ProviderStreamError:
    """
    Wrap a provider failure that happened **before any chunk was produced**.

    Opening the stream is the last moment a provider can still be swapped: the
    client has not received a single byte yet, so the dispatcher replays the
    request on another provider of the model (and afterwards on its
    ``fallback_model``).  Failures raised later - while the stream is being
    consumed - keep the historical behaviour (a final error chunk), because
    replaying a partially delivered response would corrupt it.
    """
    return ProviderStreamError(
        status_code=0,
        message=_request_error_message(exc),
        error_code=connection_error_code(exc),
    )


def _open_stream(
    endpoint: Any,
    method: str,
    url: str,
    payload: Dict[str, Any],
    headers: Dict[str, Any],
) -> Response:
    """
    Issue the streaming request of a provider.

    A transport failure means the provider never answered (connection refused,
    connect timeout, DNS failure...), i.e. nothing was produced for the client,
    so it becomes a failover signal (see :func:`_pre_content_failure`) instead
    of a stream error.
    """
    try:
        if method == "POST":
            return requests.post(
                url,
                json=payload,
                timeout=endpoint.timeout,
                stream=True,
                headers=headers,
            )
        return requests.get(
            url,
            params=payload,
            timeout=endpoint.timeout,
            stream=True,
            headers=headers,
        )
    except requests.RequestException as exc:
        raise _pre_content_failure(exc) from exc


def _guarded_body(items: Iterator[Any]) -> Iterator[Any]:
    """
    Relay provider payload items, translating a failure of the **first** read.

    A provider may answer ``200 OK`` and drop the connection before sending a
    single byte of the body (or fail while producing the very first line).  No
    chunk exists at that point, so the failure becomes the failover signal of
    :func:`_pre_content_failure` and the request is replayed on another
    provider of the model.  From the first item on the response counts as
    delivered: the original ``requests`` error propagates and the generators
    end the stream with their usual error chunk.
    """
    pending = iter(items)
    try:
        first = next(pending)
    except StopIteration:
        return
    except requests.RequestException as exc:
        raise _pre_content_failure(exc) from exc
    yield first
    yield from pending


# ------------------------------------------------#
# Helper enum for stream‑type resolution
# ------------------------------------------------#
class StreamConversion(Enum):
    """
    Flags indicating which conversion path should be taken.
    """

    OLLAMA = auto()
    OPENAI = auto()
    ANTHROPIC = auto()
    OPENAI_TO_OLLAMA = auto()
    OLLAMA_TO_OPENAI = auto()
    OPENAI_TO_LMSTUDIO = auto()
    OLLAMA_TO_LMSTUDIO = auto()
    LMSTUDIO_PASSTHROUGH = auto()
    ANTHROPIC_TO_OPENAI = auto()
    OPENAI_TO_ANTHROPIC = auto()
    VERTEX = auto()
    VERTEX_TO_OPENAI = auto()
    BEDROCK_TO_OPENAI = auto()


class StreamHandler:
    """
    Centralized helper for all streaming interactions.

    The methods mirror the previous module‑level functions but are now
    instance methods.  They still accept the ``endpoint`` argument so
    that timeout, logging, and model‑unset logic stay unchanged.
    """

    @staticmethod
    @contextlib.contextmanager
    def _model_unsetter(endpoint, payload, api_model_provider, options):
        """
        Guarantees that ``endpoint.unset_model`` is called exactly once,
        regardless of how the surrounding generator exits.
        """
        try:
            yield
        finally:
            endpoint.unset_model(
                params=payload,
                api_model_provider=api_model_provider,
                options=options,
            )

    @staticmethod
    def _log_request_error(endpoint: Any, exc: Exception) -> None:
        """
        Log a failed provider request at ``ERROR`` level (server‑side —
        the client only ever receives the sanitized error chunk).
        """
        logger = getattr(endpoint, "logger", None)
        if logger is None:
            return
        try:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        except Exception:  # pylint: disable=broad-exception-caught
            status = None
        if status is not None:
            logger.error(
                "Provider request failed: HTTP %s — %s",
                status,
                _request_error_message(exc),
            )
        else:
            logger.error("Provider request failed: %s", _request_error_message(exc))

    @staticmethod
    def _force_iter_openai(force_text: str, api_model_provider) -> Iterator[bytes]:
        """
        Generates a single forced chunk followed by a DONE marker for
        OpenAI‑style (SSE) streams.  This format is also compatible with
        LM Studio's OpenAI‑compatible API.
        """
        base_chunk = {
            "id": "chatcmpl-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
            "object": "chat.completion.chunk",
            "created": int(datetime.datetime.now().timestamp()),
            "model": api_model_provider.model_path or api_model_provider.name,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": force_text},
                    "finish_reason": None,
                }
            ],
        }
        base_chunk_str = json.dumps(base_chunk)

        def _iter() -> Iterator[bytes]:
            yield f"data: {base_chunk_str}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"

        return _iter()

    @staticmethod
    def _force_iter_lmstudio(force_text: str, api_model_provider) -> Iterator[bytes]:
        """
        Generates forced chunks in LM Studio *native* SSE format:
        - first chunk includes delta.role="assistant" and delta.content
        - final chunk has finish_reason="stop" and empty delta
        - then emits [DONE]
        """
        stable_id = "chatcmpl-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        stable_created = int(datetime.datetime.now().timestamp())
        stable_model = api_model_provider.model_path or api_model_provider.name

        first_chunk = {
            "id": stable_id,
            "object": "chat.completion.chunk",
            "created": stable_created,
            "model": stable_model,
            "system_fingerprint": stable_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": force_text},
                    "logprobs": None,
                    "finish_reason": None,
                }
            ],
        }

        final_chunk = {
            "id": stable_id,
            "object": "chat.completion.chunk",
            "created": stable_created,
            "model": stable_model,
            "system_fingerprint": stable_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "logprobs": None,
                    "finish_reason": "stop",
                }
            ],
        }

        def _iter() -> Iterator[bytes]:
            yield (
                "data: " + json.dumps(first_chunk, ensure_ascii=False) + "\n\n"
            ).encode("utf-8")
            yield (
                "data: " + json.dumps(final_chunk, ensure_ascii=False) + "\n\n"
            ).encode("utf-8")
            yield b"data: [DONE]\n\n"

        return _iter()

    def _force_iter_ollama(
        self, force_text: str, api_model_provider
    ) -> Iterator[bytes]:
        """
        Generates forced chunks for Ollama‑style NDJSON streams.
        """

        def _iter() -> Iterator[bytes]:
            yield self._ollama_chunk(
                delta=force_text, done=False, api_model_provider=api_model_provider
            )
            yield self._ollama_chunk(
                delta="", done=True, api_model_provider=api_model_provider
            )

        return _iter()

    # ------------------------------------------------#
    # Shared helper for passthrough streaming
    # ------------------------------------------------#

    def _passthrough_generator(
        self,
        method: str,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, Any],
        endpoint,
        api_model_provider,
        options: Optional[Dict[str, Any]],
    ) -> Iterator[bytes]:
        """
        Shared generator used by ``stream_openai`` and ``stream_ollama``.
        Handles the ``_model_unsetter`` context and maps request errors
        to a simple JSON error payload.
        """
        with self._model_unsetter(endpoint, payload, api_model_provider, options):
            try:
                yield from self._passthrough_stream(
                    method=method,
                    url=url,
                    endpoint=endpoint,
                    payload=payload,
                    headers=headers,
                )
            except requests.RequestException as exc:
                self._log_request_error(endpoint, exc)
                err = {"error": _request_error_message(exc)}
                # Preserve the original formatting used in the two callers
                yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                return

    # ------------------------------------------------#
    # Public streaming entry points
    # ------------------------------------------------#

    def stream_openai(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        OpenAI‑style streaming (SSE) – returns the raw SSE bytes unchanged.
        """
        if force_text is not None:

            def _iter() -> Iterator[bytes]:
                with self._model_unsetter(
                    endpoint, payload, api_model_provider, options
                ):
                    yield from self._force_iter_openai(
                        force_text or "", api_model_provider
                    )

            return _iter()

        headers["Accept"] = "text/event-stream"

        # Use the shared generator – removes duplicated try/except boilerplate
        return self._passthrough_generator(
            method=method,
            url=url,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
            api_model_provider=api_model_provider,
            options=options,
        )

    def stream_lmstudio(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        LMStudio-native streaming (SSE) – returns the raw SSE bytes unchanged.
        """
        if force_text is not None:

            def _iter() -> Iterator[bytes]:
                with self._model_unsetter(
                    endpoint, payload, api_model_provider, options
                ):
                    yield from self._force_iter_lmstudio(
                        force_text or "", api_model_provider
                    )

            return _iter()

        return self.stream_openai(
            url=url,
            payload=payload,
            method=method,
            headers=headers,
            options=options,
            endpoint=endpoint,
            api_model_provider=api_model_provider,
            force_text=force_text,
        )

    def stream_ollama(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Streaming from an Ollama endpoint – **passes the stream through unchanged**.
        """
        if force_text is not None:

            def _iter() -> Iterator[bytes]:
                with self._model_unsetter(
                    endpoint, payload, api_model_provider, options
                ):
                    yield from self._force_iter_ollama(
                        force_text or "", api_model_provider
                    )

            return _iter()

        # Re‑use the generic passthrough logic
        return self._passthrough_generator(
            method=method,
            url=url,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
            api_model_provider=api_model_provider,
            options=options,
        )

    def stream_anthropic(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Anthropic-native streaming – returns the raw SSE bytes unchanged.
        """
        headers["Accept"] = "text/event-stream"
        headers["anthropic-version"] = "2023-06-01"

        return self._passthrough_generator(
            method=method,
            url=url,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
            api_model_provider=api_model_provider,
            options=options,
        )

    def stream_anthropic_to_openai(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert Anthropic SSE stream to OpenAI-compatible SSE stream.
        """
        headers["Accept"] = "text/event-stream"
        headers["anthropic-version"] = "2023-06-01"

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    try:
                        response = requests.request(
                            method=method,
                            url=url,
                            json=payload,
                            headers=headers,
                            stream=True,
                            timeout=endpoint.timeout,
                        )
                    except requests.RequestException as exc:
                        raise _pre_content_failure(exc) from exc
                    _raise_for_status(response)

                    for line in _guarded_body(response.iter_lines()):
                        if not line:
                            continue

                        line_str = line.decode("utf-8")
                        if line_str.startswith("event: "):
                            continue

                        if line_str.startswith("data: "):
                            data_str = line_str[6:]
                            if data_str == "[DONE]":
                                yield b"data: [DONE]\n\n"
                                continue

                            try:
                                chunk = json.loads(data_str)
                                from llm_router_api.core.api_types.openai import (
                                    OpenAIConverters,
                                )

                                _fa = OpenAIConverters.FromAnthropic
                                converted = _fa.convert_stream_chunk(chunk)
                                if converted:
                                    yield f"data: {json.dumps(converted)}\n\n".encode(
                                        "utf-8"
                                    )
                            except json.JSONDecodeError:
                                continue

                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                    return

        return _iter()

    def stream_openai_to_anthropic(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert OpenAI SSE stream to Anthropic-compatible SSE stream.
        """
        # Note: Implementation of OpenAI -> Anthropic stream
        # conversion is more complex because OpenAI doesn't
        # map 1:1 to Anthropic events.
        # For now, use passthrough when possible; raise if conversion needed.
        # In most cases, we want to go TO OpenAI format.
        headers["Accept"] = "text/event-stream"
        return self._passthrough_generator(
            method=method,
            url=url,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
            api_model_provider=api_model_provider,
            options=options,
        )

    def stream_vertex(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Vertex AI (Gemini)‑native streaming (SSE) – returns the raw SSE
        bytes unchanged.
        """
        if force_text is not None:

            def _force_iter() -> Iterator[bytes]:
                with self._model_unsetter(
                    endpoint, payload, api_model_provider, options
                ):
                    yield from self._force_iter_openai(
                        force_text or "", api_model_provider
                    )

            return _force_iter()

        headers["Accept"] = "text/event-stream"
        return self._passthrough_generator(
            method=method,
            url=url,
            payload=payload,
            headers=headers,
            endpoint=endpoint,
            api_model_provider=api_model_provider,
            options=options,
        )

    def stream_vertex_to_openai(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert a Vertex AI (Gemini) ``streamGenerateContent`` SSE stream
        into an OpenAI‑compatible SSE stream.
        """
        if force_text is not None:

            def _force_iter() -> Iterator[bytes]:
                with self._model_unsetter(
                    endpoint, payload, api_model_provider, options
                ):
                    yield from self._force_iter_openai(
                        force_text or "", api_model_provider
                    )

            return _force_iter()

        headers["Accept"] = "text/event-stream"

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    try:
                        response = requests.request(
                            method=method,
                            url=url,
                            json=payload,
                            headers=headers,
                            stream=True,
                            timeout=endpoint.timeout,
                        )
                    except requests.RequestException as exc:
                        raise _pre_content_failure(exc) from exc
                    _raise_for_status(response)

                    ctx = VertexAiConverters.FromGemini.new_stream_ctx(
                        model=(
                            (
                                api_model_provider.model_path
                                if api_model_provider.model_path
                                else api_model_provider.name
                            )
                            if api_model_provider is not None
                            else ""
                        )
                    )
                    finish_sent = False
                    done_sent = False
                    for line in _guarded_body(response.iter_lines()):
                        if not line:
                            continue

                        line_str = line.decode("utf-8")
                        if not line_str.startswith("data:"):
                            continue

                        data_str = line_str[5:].strip()
                        if data_str == "[DONE]":
                            yield b"data: [DONE]\n\n"
                            done_sent = True
                            continue

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        converted = (
                            VertexAiConverters.FromGemini.convert_stream_chunk(
                                chunk, ctx
                            )
                        )
                        if converted:
                            if (converted.get("choices") or [{}])[0].get(
                                "finish_reason"
                            ):
                                finish_sent = True
                            yield f"data: {json.dumps(converted)}\n\n".encode(
                                "utf-8"
                            )

                    # Gemini's native SSE carries neither the OpenAI ``[DONE]``
                    # sentinel nor (for unmapped reasons) a terminal finish
                    # reason, so close the stream the way OpenAI clients expect.
                    # Reached only on a clean end: a pre‑content failure raised
                    # above, and a mid‑stream error returned after its error
                    # chunk — matching the other ``*_to_openai`` helpers.
                    if not finish_sent:
                        final = VertexAiConverters.FromGemini.new_final_chunk(
                            ctx,
                            VertexAiConverters.map_finish_reason(
                                None, bool(ctx.get("tool_call_seen"))
                            ),
                        )
                        yield f"data: {json.dumps(final)}\n\n".encode("utf-8")
                    if not done_sent:
                        yield b"data: [DONE]\n\n"

                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                    return

        return _iter()

    def stream_bedrock_to_openai(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert a Bedrock ``converse-stream`` event stream into OpenAI SSE.

        Two things set this apart from the other ``*_to_openai`` helpers:

        * the response is an **Amazon event stream** (binary framing), not SSE,
          so the bytes go through :func:`iter_events` rather than a ``data:``
          line scan;
        * the request is signed with SigV4, which covers the body — so the body
          is serialised here, once, and sent as ``data`` instead of ``json``.
          Signing at :func:`ApiTypesDispatcher.request_headers` time (the point
          the generic streaming path builds its headers) is impossible, because
          the body is not yet serialised there.
        """
        if force_text is not None:

            def _force_iter() -> Iterator[bytes]:
                with self._model_unsetter(
                    endpoint, payload, api_model_provider, options
                ):
                    yield from self._force_iter_openai(
                        force_text or "", api_model_provider
                    )

            return _force_iter()

        api_type = (
            api_model_provider.api_type
            if api_model_provider is not None
            else "bedrock"
        )
        body = ApiTypesDispatcher.signed_body(payload)
        signed_headers = ApiTypesDispatcher.sign_request(
            api_type,
            api_model_provider,
            method,
            url,
            dict(headers or {}),
            body,
        )
        signed_headers.setdefault("Content-Type", "application/json")
        signed_headers["Accept"] = "application/vnd.amazon.eventstream"

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    try:
                        response = requests.request(
                            method=method,
                            url=url,
                            data=body,
                            headers=signed_headers,
                            stream=True,
                            timeout=endpoint.timeout,
                        )
                    except requests.RequestException as exc:
                        raise _pre_content_failure(exc) from exc
                    _raise_for_status(response)

                    ctx = BedrockConverters.FromBedrock.new_stream_ctx(
                        model=(
                            (
                                api_model_provider.model_path
                                if api_model_provider.model_path
                                else api_model_provider.name
                            )
                            if api_model_provider is not None
                            else ""
                        )
                    )
                    finish_sent = False
                    try:
                        for event_type, event in iter_events(
                            _guarded_body(response.iter_content(chunk_size=8192))
                        ):
                            converted = BedrockConverters.FromBedrock.convert_event(
                                event_type, event, ctx
                            )
                            if not converted:
                                continue
                            if (converted.get("choices") or [{}])[0].get(
                                "finish_reason"
                            ):
                                finish_sent = True
                            yield f"data: {json.dumps(converted)}\n\n".encode(
                                "utf-8"
                            )
                    except AwsEventStreamError as exc:
                        # A service error frame, a failed frame CRC or a stream
                        # cut mid‑frame: the client already received content, so
                        # report it as a stream error rather than failing over.
                        self._log_request_error(endpoint, exc)
                        err = {"error": sanitize_error_message(str(exc))}
                        yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                        return

                    # Bedrock closes with ``messageStop``/``metadata``, which this
                    # conversion turns into the terminal chunk only here: no
                    # in‑band event carries an OpenAI ``finish_reason``, and the
                    # native stream has no ``[DONE]`` sentinel at all.
                    if not finish_sent:
                        final = BedrockConverters.FromBedrock.flush(ctx)
                        yield f"data: {json.dumps(final)}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"

                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                    return

        return _iter()

    @staticmethod
    def _passthrough_stream(
        method, url, endpoint, payload, headers
    ) -> Iterator[bytes]:
        resp = _open_stream(endpoint, method, url, payload, headers)

        with resp as r:
            _raise_for_status(r)
            for chunk in _guarded_body(r.iter_content(chunk_size=None)):
                if chunk:
                    yield chunk

    def stream_openai_to_ollama(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert an OpenAI‑style (SSE) stream to Ollama NDJSON.

        This also covers: LM Studio (OpenAI‑compatible) → Ollama.
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_ollama(force_text, api_model_provider)

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    req = _open_stream(endpoint, method, url, payload, headers)
                    with req as resp:
                        _raise_for_status(resp)
                        yield from _guarded_body(
                            self._parse_ollama_stream(resp, api_model_provider)
                        )
                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield (json.dumps(err) + "\n").encode("utf-8")
                    return

        return _iter()

    def stream_ollama_to_openai(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert an Ollama NDJSON stream to OpenAI‑compatible SSE.

        This enables: Ollama → OpenAI endpoint and Ollama → LM Studio
        (because LM Studio expects OpenAI‑compatible SSE).
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_openai(force_text, api_model_provider)

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint=endpoint,
                payload=payload,
                api_model_provider=api_model_provider,
                options=options,
            ):
                try:
                    ctx = _open_stream(endpoint, method, url, payload, headers)
                    with ctx as resp:
                        _raise_for_status(resp)
                        for raw_line in _guarded_body(
                            resp.iter_lines(decode_unicode=False)
                        ):
                            if not raw_line:
                                continue
                            try:
                                ollama_obj = json.loads(
                                    raw_line.decode("utf-8", errors="replace")
                                )
                            except Exception:
                                # Forward unparseable line unchanged
                                yield raw_line + b"\n"
                                continue

                            # Build a base SSE chunk
                            base = {
                                "id": "chatcmpl-"
                                + datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
                                "object": "chat.completion.chunk",
                                "created": int(datetime.datetime.now().timestamp()),
                                "model": api_model_provider.model_path
                                or api_model_provider.name,
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {},
                                        "finish_reason": None,
                                    }
                                ],
                            }

                            if ollama_obj.get("done"):
                                base["choices"][0]["finish_reason"] = "stop"
                                yield (
                                    "data: "
                                    + json.dumps(base, ensure_ascii=False)
                                    + "\n\n"
                                ).encode("utf-8")
                                yield b"data: [DONE]\n\n"
                                continue

                            delta_text = ollama_obj.get("message", {}).get(
                                "content", ""
                            )
                            if delta_text:
                                base["choices"][0]["delta"] = {"content": delta_text}
                                yield (
                                    "data: "
                                    + json.dumps(base, ensure_ascii=False)
                                    + "\n\n"
                                ).encode("utf-8")
                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield ("data: " + json.dumps(err) + "\n\n").encode("utf-8")
                    return

        return _iter()

    def stream_openai_to_lmstudio(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert an OpenAI‑compatible SSE stream (e.g. vLLM) into LM Studio's *native*
        SSE chunk shape.

        Key differences we normalise:
        - LM Studio usually includes ``system_fingerprint``
        - LM Studio sends ``delta.role="assistant"`` in the first emitted chunk
        - Keep only the fields LM Studio expects (but do **not** break SSE framing)
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_openai(force_text, api_model_provider)

        headers.update(
            {
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )

        def _iter() -> Iterator[bytes]:
            stable_id: Optional[str] = None
            stable_created: Optional[int] = None
            stable_model: Optional[str] = None
            role_sent = False

            def _as_lmstudio_sse(event_obj_i: Dict[str, Any]) -> bytes:
                nonlocal stable_id, stable_created, stable_model, role_sent

                # Capture stable metadata from the first parsable chunk
                if stable_id is None and isinstance(event_obj_i.get("id"), str):
                    stable_id = event_obj_i["id"]
                if stable_created is None and isinstance(
                    event_obj_i.get("created"), int
                ):
                    stable_created = event_obj_i["created"]
                if stable_model is None and isinstance(
                    event_obj_i.get("model"), str
                ):
                    stable_model = event_obj_i["model"]

                out: Dict[str, Any] = {
                    "id": stable_id
                    or event_obj_i.get("id")
                    or (
                        "chatcmpl-"
                        + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    ),
                    "object": event_obj_i.get("object") or "chat.completion.chunk",
                    "created": (
                        stable_created
                        if stable_created is not None
                        else int(datetime.datetime.now().timestamp())
                    ),
                    "model": stable_model
                    or (api_model_provider.model_path or api_model_provider.name),
                    "system_fingerprint": api_model_provider.model_path
                    or api_model_provider.name,
                    "choices": [],
                }

                choices = event_obj_i.get("choices") or []
                if not isinstance(choices, list) or not choices:
                    out["choices"] = [
                        {
                            "index": 0,
                            "delta": {},
                            "logprobs": None,
                            "finish_reason": None,
                        }
                    ]
                else:
                    new_choices = []
                    for ch in choices:
                        if not isinstance(ch, dict):
                            continue
                        new_choice = {
                            "index": ch.get("index", 0),
                            "delta": ch.get("delta") or {},
                            "logprobs": ch.get("logprobs", None),
                            "finish_reason": ch.get("finish_reason", None),
                        }

                        # Normalise delta shape
                        if not isinstance(new_choice["delta"], dict):
                            new_choice["delta"] = {}

                        # LM Studio expects a role on the first emitted chunk
                        if not role_sent:
                            if "role" not in new_choice["delta"]:
                                new_choice["delta"]["role"] = "assistant"
                            role_sent = True

                        # Keep only role/content
                        allowed_delta = {}
                        if "role" in new_choice["delta"]:
                            allowed_delta["role"] = new_choice["delta"]["role"]
                        if "content" in new_choice["delta"]:
                            allowed_delta["content"] = new_choice["delta"]["content"]
                        new_choice["delta"] = allowed_delta

                        new_choices.append(new_choice)

                    out["choices"] = new_choices or [
                        {
                            "index": 0,
                            "delta": {"role": "assistant"} if not role_sent else {},
                            "logprobs": None,
                            "finish_reason": None,
                        }
                    ]

                return (
                    "data: " + json.dumps(out, ensure_ascii=False) + "\n\n"
                ).encode("utf-8")

            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    resp = _open_stream(endpoint, method, url, payload, headers)

                    with resp:
                        _raise_for_status(resp)
                        for raw_line in _guarded_body(
                            resp.iter_lines(decode_unicode=False)
                        ):
                            if not raw_line:
                                continue
                            line = raw_line.strip()

                            # Pass‑through non‑data lines unchanged
                            if not line.startswith(b"data:"):
                                yield b"data: " + line + b"\n\n"
                                continue

                            data = line[5:].strip()
                            if data == b"[DONE]":
                                yield b"data: [DONE]\n\n"
                                continue

                            try:
                                event_obj = json.loads(
                                    data.decode("utf-8", errors="replace")
                                )
                            except Exception:
                                yield b"data: " + data + b"\n\n"
                                continue

                            yield _as_lmstudio_sse(event_obj)

                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                    return

        return _iter()

    def stream_ollama_to_lmstudio(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        endpoint,
        api_model_provider,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Convert an Ollama NDJSON stream into LM Studio’s native SSE format.

        LM Studio’s native format is *very close* to OpenAI SSE, but in practice:
        - it typically includes ``system_fingerprint``
        - it often emits ``delta.role="assistant"`` on the first chunk
        - Metadata like ``id``/``created``/``model`` stays stable across chunks
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_openai(force_text, api_model_provider)

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint=endpoint,
                payload=payload,
                api_model_provider=api_model_provider,
                options=options,
            ):
                stable_id = "chatcmpl-" + datetime.datetime.now().strftime(
                    "%Y%m%d%H%M%S"
                )
                stable_created = int(datetime.datetime.now().timestamp())
                stable_model = (
                    api_model_provider.model_path or api_model_provider.name
                )
                role_sent = False

                def _lmstudio_event(
                    delta: Dict[str, Any], finish_reason: Optional[str]
                ) -> bytes:
                    nonlocal role_sent
                    if not role_sent:
                        if "role" not in delta:
                            delta = {"role": "assistant", **delta}
                        role_sent = True

                    obj = {
                        "id": stable_id,
                        "object": "chat.completion.chunk",
                        "created": stable_created,
                        "model": stable_model,
                        "system_fingerprint": stable_model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": delta,
                                "logprobs": None,
                                "finish_reason": finish_reason,
                            }
                        ],
                    }
                    return (
                        "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"
                    ).encode("utf-8")

                try:
                    ctx = _open_stream(endpoint, method, url, payload, headers)

                    with ctx as resp:
                        _raise_for_status(resp)
                        for raw_line in _guarded_body(
                            resp.iter_lines(decode_unicode=False)
                        ):
                            if not raw_line:
                                continue
                            try:
                                ollama_obj = json.loads(
                                    raw_line.decode("utf-8", errors="replace")
                                )
                            except Exception:
                                yield b"data: " + raw_line + b"\n\n"
                                continue

                            if ollama_obj.get("done"):
                                yield _lmstudio_event(delta={}, finish_reason="stop")
                                yield b"data: [DONE]\n\n"
                                return

                            delta_text = ollama_obj.get("message", {}).get(
                                "content", ""
                            )
                            if delta_text:
                                yield _lmstudio_event(
                                    delta={"content": delta_text}, finish_reason=None
                                )

                except requests.RequestException as exc:
                    self._log_request_error(endpoint, exc)
                    err = {"error": _request_error_message(exc)}
                    yield ("data: " + json.dumps(err) + "\n\n").encode("utf-8")
                    return

        return _iter()

    # ------------------------------------------------#
    # Helper utilities (kept private to this class)
    # ------------------------------------------------#

    @staticmethod
    def _ollama_chunk(
        delta: str,
        done: bool = False,
        usage: Optional[Dict[str, int]] = None,
        api_model_provider=None,
    ) -> bytes:
        """
        Build a single Ollama‑compatible NDJSON line.
        """
        obj = {
            "model": api_model_provider.model_path or api_model_provider.name,
            "created_at": datetime.datetime.now().isoformat() + "Z",
            "done": done,
            "message": {},
            "eval_count": 0,
            "prompt_eval_count": 0,
        }

        if not done:
            obj["message"] = {"role": "assistant", "content": delta}
        else:
            obj["message"] = {"role": "assistant", "content": ""}
            if usage:
                obj["prompt_eval_count"] = usage.get("prompt_tokens", 0)
                obj["eval_count"] = usage.get("completion_tokens", 0)
            obj["total_duration"] = 0
            obj["load_duration"] = 0
            obj["prompt_eval_duration"] = 0
            obj["eval_duration"] = 0

        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

    def _parse_ollama_stream(
        self, response: Response, api_model_provider
    ) -> Iterator[bytes]:
        """
        Convert an OpenAI‑style SSE/NDJSON stream into Ollama NDJSON chunks.
        """
        sent_done = False
        usage_data = None
        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                continue

            # ---- SSE “data:” lines ----
            if line.startswith("data:"):
                data = line[5:].strip()
                if data == "[DONE]":
                    if not sent_done:
                        yield self._ollama_chunk(
                            delta="",
                            done=True,
                            usage=usage_data,
                            api_model_provider=api_model_provider,
                        )
                        sent_done = True
                    continue
                try:
                    event = json.loads(data)
                except Exception:
                    yield (line + "\n").encode("utf-8")
                    continue

                if "usage" in event:
                    usage_data = event["usage"]

                # Extract delta text
                delta_text = ""
                choices = event.get("choices", [])
                if choices:
                    delta_obj = (
                        choices[0].get("delta") or choices[0].get("text") or {}
                    )
                    if isinstance(delta_obj, dict):
                        delta_text = delta_obj.get("content") or ""
                    elif isinstance(delta_obj, str):
                        delta_text = delta_obj

                if delta_text:
                    yield self._ollama_chunk(
                        delta=delta_text,
                        done=False,
                        api_model_provider=api_model_provider,
                    )

                # Final chunk on finish_reason
                if choices and choices[0].get("finish_reason") and not sent_done:
                    yield self._ollama_chunk(
                        delta="",
                        done=True,
                        usage=usage_data,
                        api_model_provider=api_model_provider,
                    )
                    sent_done = True
                continue

            # ---- Plain NDJSON line ----
            try:
                evt = json.loads(line)
            except Exception:
                yield (line + "\n").encode("utf-8")
                continue

            if "usage" in evt:
                usage_data = evt["usage"]

            delta_text = ""
            if "choices" in evt:
                ch = evt["choices"]
                if ch:
                    d = ch[0].get("delta") or ch[0].get("text") or {}
                    if isinstance(d, dict):
                        delta_text = d.get("content") or ""
                    elif isinstance(d, str):
                        delta_text = d
                if delta_text:
                    yield self._ollama_chunk(
                        delta=delta_text,
                        done=False,
                        api_model_provider=api_model_provider,
                    )
                if ch and ch[0].get("finish_reason") and not sent_done:
                    yield self._ollama_chunk(
                        delta="",
                        done=True,
                        usage=usage_data,
                        api_model_provider=api_model_provider,
                    )
                    sent_done = True
            elif evt.get("done") is True and not sent_done:
                yield self._ollama_chunk(
                    delta="",
                    done=True,
                    usage=usage_data,
                    api_model_provider=api_model_provider,
                )
                sent_done = True
            else:
                yield (line + "\n").encode("utf-8")

        if not sent_done:
            yield self._ollama_chunk(
                delta="",
                done=True,
                usage=usage_data,
                api_model_provider=api_model_provider,
            )

    # ------------------------------------------------#
    # Stream‑type resolution – moved from EndpointWithHttpRequestI
    # ------------------------------------------------#

    @staticmethod
    def resolve_stream_type(
        endpoint_ep_types: list, api_model_provider
    ) -> Optional[StreamConversion]:
        """
        Determine which streaming conversion should be applied.

        Returns the matching ``StreamConversion`` enum value, or ``None``
        when no conversion is needed (endpoint and provider are both
        OpenAI-compatible).
        """
        provider_type = str(api_model_provider.api_type)

        # ------------------------------------#
        # Determine what the endpoint expects
        # ------------------------------------#
        endpoint_wants_ollama = "ollama" in endpoint_ep_types
        endpoint_wants_anthropic = "anthropic" in endpoint_ep_types
        endpoint_wants_lmstudio = endpoint_ep_types == ["lmstudio"]
        endpoint_wants_vertex = "vertex_ai" in endpoint_ep_types
        if endpoint_wants_lmstudio:
            endpoint_wants_openai = False
        else:
            endpoint_wants_openai = bool(
                set(OPENAI_COMPATIBLE_PROVIDERS).intersection(endpoint_ep_types)
            )

        # ------------------------------------#
        # Provider capabilities
        # ------------------------------------#
        provider_is_ollama = provider_type == "ollama"
        provider_is_lmstudio = provider_type == "lmstudio"
        provider_is_anthropic = provider_type == "anthropic"
        provider_is_vertex = provider_type == "vertex_ai"
        provider_is_bedrock = provider_type == "bedrock"
        provider_is_openai = (
            provider_type in OPENAI_COMPATIBLE_PROVIDERS
            if not provider_is_lmstudio and not provider_is_anthropic
            else False
        )

        # ------------------------------------#
        # Initialise flags – all start as ``False``
        # ------------------------------------#
        flags = {
            StreamConversion.OPENAI_TO_OLLAMA: False,
            StreamConversion.OLLAMA_TO_OPENAI: False,
            StreamConversion.OLLAMA: False,
            StreamConversion.OPENAI: False,
            StreamConversion.OPENAI_TO_LMSTUDIO: False,
            StreamConversion.OLLAMA_TO_LMSTUDIO: False,
            StreamConversion.LMSTUDIO_PASSTHROUGH: False,
            StreamConversion.ANTHROPIC_TO_OPENAI: False,
            StreamConversion.OPENAI_TO_ANTHROPIC: False,
            StreamConversion.ANTHROPIC: False,
            StreamConversion.VERTEX_TO_OPENAI: False,
            StreamConversion.VERTEX: False,
            StreamConversion.BEDROCK_TO_OPENAI: False,
        }

        # ------------------------------------#
        # Passthrough cases
        # ------------------------------------#
        if endpoint_wants_ollama and provider_is_ollama:
            flags[StreamConversion.OLLAMA] = True
        elif endpoint_wants_anthropic and provider_is_anthropic:
            flags[StreamConversion.ANTHROPIC] = True
        elif endpoint_wants_vertex and provider_is_vertex:
            flags[StreamConversion.VERTEX] = True
        elif endpoint_wants_openai and provider_is_openai:
            flags[StreamConversion.OPENAI] = True
        elif endpoint_wants_lmstudio and provider_is_lmstudio:
            # LMStudio → LMStudio (passthrough)
            flags[StreamConversion.LMSTUDIO_PASSTHROUGH] = True

        # ------------------------------------#
        # Conversion cases
        # ------------------------------------#
        elif endpoint_wants_ollama and provider_is_openai:
            flags[StreamConversion.OPENAI_TO_OLLAMA] = True
        elif endpoint_wants_ollama and provider_is_lmstudio:
            flags[StreamConversion.OPENAI_TO_OLLAMA] = True
        elif endpoint_wants_ollama and provider_is_anthropic:
            # Maybe implement ANTHROPIC_TO_OLLAMA if needed, for now use openai as
            # middleman or fail
            pass
        elif endpoint_wants_openai and provider_is_ollama:
            flags[StreamConversion.OLLAMA_TO_OPENAI] = True
        elif endpoint_wants_openai and provider_is_lmstudio:
            flags[StreamConversion.OPENAI] = True
        elif endpoint_wants_openai and provider_is_anthropic:
            flags[StreamConversion.ANTHROPIC_TO_OPENAI] = True
        elif endpoint_wants_anthropic and provider_is_openai:
            flags[StreamConversion.OPENAI_TO_ANTHROPIC] = True
        elif endpoint_wants_openai and provider_is_vertex:
            flags[StreamConversion.VERTEX_TO_OPENAI] = True
        elif endpoint_wants_openai and provider_is_bedrock:
            # Bedrock streams a binary event stream, never SSE: the dedicated
            # conversion is the only path that can produce OpenAI chunks.
            flags[StreamConversion.BEDROCK_TO_OPENAI] = True

        # ------------------------------------#
        # Native LMStudio conversion checks (must be after passthrough)
        # ------------------------------------#
        elif endpoint_wants_lmstudio and provider_is_openai:
            flags[StreamConversion.OPENAI_TO_LMSTUDIO] = True
        elif endpoint_wants_lmstudio and provider_is_ollama:
            flags[StreamConversion.OLLAMA_TO_LMSTUDIO] = True

        # ------------------------------------#
        # Return the single matching enum (exactly one flag is True)
        # ------------------------------------#
        for conv, flag in flags.items():
            if flag:
                return conv
        return None
