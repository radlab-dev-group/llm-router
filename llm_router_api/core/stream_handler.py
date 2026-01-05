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

from requests import Response
from typing import Iterator, Dict, Any, Optional

from llm_router_api.base.constants_base import OPENAI_COMPATIBLE_PROVIDERS


class StreamHandler:
    """
    Centralised helper for all streaming interactions.

    The methods mirror the previous module‑level functions but are now
    instance methods.  They still accept the ``endpoint`` argument so
    that timeout, logging and model‑unset logic stay unchanged.
    """

    # --------------------------------------------------------------------- #
    # Internal utilities – extracted to avoid repetition
    # --------------------------------------------------------------------- #

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
    def _force_iter_openai(force_text: str, api_model_provider) -> Iterator[bytes]:
        """
        Generates a single forced chunk followed by a DONE marker for
        OpenAI-style (SSE) streams. This format is also compatible with
        LM Studio's OpenAI-compatible API.
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

    def _force_iter_ollama(
        self, force_text: str, api_model_provider
    ) -> Iterator[bytes]:
        """
        Generates forced chunks for Ollama-style NDJSON streams.
        """

        def _iter() -> Iterator[bytes]:
            yield self._ollama_chunk(
                delta=force_text, done=False, api_model_provider=api_model_provider
            )
            yield self._ollama_chunk(
                delta="", done=True, api_model_provider=api_model_provider
            )

        return _iter()

    # --------------------------------------------------------------------- #
    # Public streaming entry points
    # --------------------------------------------------------------------- #

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
        OpenAI-style streaming (SSE) – returns the raw SSE bytes unchanged.

        Note: This is also suitable for LM Studio when using its OpenAI-compatible API.
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_openai(force_text, api_model_provider)

        # Ensure we accept an SSE format
        headers["Accept"] = "text/event-stream"

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    for _ch in self._passthrough_stream(
                        method=method,
                        url=url,
                        endpoint=endpoint,
                        payload=payload,
                        headers=headers,
                    ):
                        yield _ch
                except requests.RequestException as exc:
                    err = {"error": str(exc)}
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")

        return _iter()

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
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_ollama(force_text, api_model_provider)

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    for _ch in self._passthrough_stream(
                        method=method,
                        url=url,
                        endpoint=endpoint,
                        payload=payload,
                        headers=headers,
                    ):
                        yield _ch
                except requests.RequestException as exc:
                    err = {"error": str(exc)}
                    yield (json.dumps(err) + "\n").encode("utf-8")

        return _iter()

    @staticmethod
    def _passthrough_stream(
        method, url, endpoint, payload, headers
    ) -> Iterator[bytes]:
        request_kwargs = {
            "url": url,
            "timeout": endpoint.timeout,
            "stream": True,
            "headers": headers,
        }
        if method == "POST":
            request_kwargs["json"] = payload
            resp = requests.post(**request_kwargs)
        else:
            request_kwargs["params"] = payload
            resp = requests.get(**request_kwargs)

        with resp as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=None):
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
        Convert an OpenAI-style (SSE) stream to Ollama NDJSON.

        This also covers: LM Studio (OpenAI-compatible) -> Ollama.
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
                    if method == "POST":
                        req = requests.post(
                            url,
                            json=payload,
                            timeout=endpoint.timeout,
                            stream=True,
                            headers=headers,
                        )
                    else:
                        req = requests.get(
                            url,
                            params=payload,
                            timeout=endpoint.timeout,
                            stream=True,
                            headers=headers,
                        )
                    with req as resp:
                        resp.raise_for_status()
                        for chunk in self._parse_ollama_stream(
                            resp, api_model_provider
                        ):
                            yield chunk
                except requests.RequestException as exc:
                    err = {"error": str(exc)}
                    yield (json.dumps(err) + "\n").encode("utf-8")

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
        Convert an Ollama NDJSON stream to OpenAI-compatible SSE.

        This enables: Ollama -> OpenAI endpoint and Ollama -> LM Studio
        (because LM Studio expects OpenAI-compatible SSE).
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
                    if method == "POST":
                        ctx = requests.post(
                            url,
                            json=payload,
                            timeout=endpoint.timeout,
                            stream=True,
                            headers=headers,
                        )
                    else:
                        ctx = requests.get(
                            url,
                            params=payload,
                            timeout=endpoint.timeout,
                            stream=True,
                            headers=headers,
                        )
                    with ctx as resp:
                        resp.raise_for_status()
                        for raw_line in resp.iter_lines(decode_unicode=False):
                            if not raw_line:
                                continue
                            try:
                                ollama_obj = json.loads(
                                    raw_line.decode("utf-8", errors="replace")
                                )
                            except Exception:
                                # Forward unparseable line unchanged
                                yield (raw_line + b"\n")
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
                    err = {"error": str(exc)}
                    yield ("data: " + json.dumps(err) + "\n\n").encode("utf-8")

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
        Stream an OpenAI‑style SSE response **as‑is** to LMStudio.

        LMStudio’s native streaming endpoint expects the same Server‑Sent‑Events
        format that the OpenAI API provides, so no conversion is required.
        """
        if force_text is not None:
            # Forced‑chunk (useful for tests / UI “thinking” state)
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_openai(force_text, api_model_provider)

        # ----- SSE‑specific request headers -----
        headers.update(
            {
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )

        def _iter() -> Iterator[bytes]:
            print(
                f"stream_openai_to_lmstudio START – url={url} method={method} payload={payload}"
            )
            done_sent = False  # track whether the upstream sent [DONE]

            # -------------------------------------------------
            # 1️⃣  Stream the upstream SSE inside the unsetter.
            # -------------------------------------------------
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    for chunk in self._passthrough_stream(
                        method=method,
                        url=url,
                        endpoint=endpoint,
                        payload=payload,
                        headers=headers,
                    ):
                        if chunk:
                            print(
                                f"stream_openai_to_lmstudio RECEIVED chunk: {chunk.decode('utf-8', errors='replace')}"
                            )
                            if b"data: [DONE]" in chunk:
                                done_sent = True
                                print(
                                    "stream_openai_to_lmstudio DETECTED upstream DONE"
                                )
                            yield chunk
                except requests.RequestException as exc:
                    err = {"error": str(exc)}
                    print(f"stream_openai_to_lmstudio RequestException: {exc}")
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                    return
                except Exception as exc:
                    err = {"error": f"Connection error: {str(exc)}"}
                    print("stream_openai_to_lmstudio Unexpected exception")
                    yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                    return

            # -------------------------------------------------
            # 2️⃣  Emit the final DONE marker **only** if the upstream
            #     didn’t already send one, then terminate the generator.
            # -------------------------------------------------
            if not done_sent:
                print(
                    "stream_openai_to_lmstudio EMIT final DONE (upstream lacked it)"
                )
                yield b"data: [DONE]\n\n"
            else:
                print(
                    "stream_openai_to_lmstudio SKIP final DONE (already sent upstream)"
                )

            print("stream_openai_to_lmstudio END")
            # Explicitly stop the generator – no extra bytes are sent.
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
        Convert an Ollama NDJSON stream into LMStudio’s native SSE format.

        This is essentially the same conversion performed by
        ``stream_ollama_to_openai``, because LMStudio’s native format
        matches the OpenAI‑compatible SSE layout.
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_openai(force_text, api_model_provider)

        # LMStudio expects SSE, so we keep the usual JSON‑NDJSON request
        # headers unchanged; the conversion logic below builds proper SSE chunks.
        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint=endpoint,
                payload=payload,
                api_model_provider=api_model_provider,
                options=options,
            ):
                try:
                    if method == "POST":
                        ctx = requests.post(
                            url,
                            json=payload,
                            timeout=endpoint.timeout,
                            stream=True,
                            headers=headers,
                        )
                    else:
                        ctx = requests.get(
                            url,
                            params=payload,
                            timeout=endpoint.timeout,
                            stream=True,
                            headers=headers,
                        )
                    with ctx as resp:
                        resp.raise_for_status()
                        for raw_line in resp.iter_lines(decode_unicode=False):
                            if not raw_line:
                                continue
                            try:
                                ollama_obj = json.loads(
                                    raw_line.decode("utf-8", errors="replace")
                                )
                            except Exception:
                                # Forward unparseable line unchanged
                                yield (raw_line + b"\n")
                                continue

                            # Build a base SSE chunk (same as in stream_ollama_to_openai)
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
                    err = {"error": str(exc)}
                    yield ("data: " + json.dumps(err) + "\n\n").encode("utf-8")

        return _iter()

    # --------------------------------------------------------------------- #
    # Helper utilities (kept private to this class)
    # --------------------------------------------------------------------- #

    @staticmethod
    def _ollama_chunk(
        delta: str,
        done: bool = False,
        usage: Optional[Dict[str, int]] = None,
        api_model_provider=None,
    ) -> bytes:
        """
        Build a single Ollama-compatible NDJSON line.
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
        Convert an OpenAI-style SSE/NDJSON stream into Ollama NDJSON chunks.
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

    # --------------------------------------------------------------------- #
    # Stream-type resolution – moved from EndpointWithHttpRequestI
    # --------------------------------------------------------------------- #

    @staticmethod
    def resolve_stream_type(
        endpoint_ep_types: list, api_model_provider
    ) -> tuple[bool, bool, bool, bool, bool, bool]:
        """
        Determine which streaming conversion should be applied.

        New support added for *native* LMStudio streaming:
        - OpenAI‑style → LMStudio   → ``is_openai_to_lmstudio``
        - Ollama      → LMStudio   → ``is_ollama_to_lmstudio``

        Existing conversions remain:
        - Ollama → LMStudio (via OpenAI‑compatible API) → ``is_ollama_to_openai``
        - OpenAI‑compatible → Ollama               → ``is_openai_to_ollama``
        - Direct passthrough for Ollama, OpenAI‑compatible or LMStudio

        Returns a tuple:
        (is_openai_to_ollama, is_ollama_to_openai,
         is_ollama, is_openai,
         is_openai_to_lmstudio, is_ollama_to_lmstudio)
        """
        provider_type = str(api_model_provider.api_type)

        # Endpoint expectations
        endpoint_wants_ollama = "ollama" in endpoint_ep_types
        endpoint_wants_lmstudio = endpoint_ep_types == ["lmstudio"]
        if endpoint_wants_lmstudio:
            endpoint_wants_openai = False
        else:
            endpoint_wants_openai = (
                len(
                    set(OPENAI_COMPATIBLE_PROVIDERS).intersection(
                        set(endpoint_ep_types)
                    )
                )
                > 0
            )

        provider_is_ollama = provider_type == "ollama"
        provider_is_lmstudio = provider_type == "lmstudio"
        if provider_is_lmstudio:
            provider_is_openai = False
        else:
            provider_is_openai = provider_type in OPENAI_COMPATIBLE_PROVIDERS

        # Conversion flags
        is_openai_to_ollama = False
        is_ollama_to_openai = False
        is_ollama = False
        is_openai = False
        # New native LMStudio conversion flags
        is_openai_to_lmstudio = False
        is_ollama_to_lmstudio = False

        # -----------------------------------------------------------------
        # Passthrough types
        # Ollama -> Ollama
        if endpoint_wants_ollama and provider_is_ollama:
            is_ollama = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # OpenAI-like -> OpenAI-like
        if endpoint_wants_openai and provider_is_openai:
            is_openai = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # LMStudio -> LMStudio
        if endpoint_wants_lmstudio and provider_is_lmstudio:
            is_openai = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )

        # -----------------------------------------------------------------
        # Conversions
        # OpenAI-like -> Ollama
        if endpoint_wants_ollama and provider_is_openai:
            is_openai_to_ollama = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # LMStudio -> Ollama
        if endpoint_wants_ollama and provider_is_lmstudio:
            is_openai_to_ollama = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # Ollama -> OpenAI-like
        if endpoint_wants_openai and provider_is_ollama:
            is_ollama_to_openai = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # LMStudio -> OpenAI-like
        if endpoint_wants_openai and provider_is_lmstudio:
            is_openai = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )

        # -----------------------------------------------------------------
        # New native LMStudio conversion checks (must come after the
        # passthrough branches above)
        # OpenAI‑compatible → LMStudio (native)
        if endpoint_wants_lmstudio and provider_is_openai:
            is_openai_to_lmstudio = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # Ollama → LMStudio (native)
        if endpoint_wants_lmstudio and provider_is_ollama:
            is_ollama_to_lmstudio = True
            return (
                is_openai_to_ollama,
                is_ollama_to_openai,
                is_ollama,
                is_openai,
                is_openai_to_lmstudio,
                is_ollama_to_lmstudio,
            )
        # default: no special conversion flags
        return (
            is_openai_to_ollama,
            is_ollama_to_openai,
            is_ollama,
            is_openai,
            is_openai_to_lmstudio,
            is_ollama_to_lmstudio,
        )
