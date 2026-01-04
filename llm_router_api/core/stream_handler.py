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
    def _force_iter_generic(force_text: str, api_model_provider) -> Iterator[bytes]:
        """
        Generates a single forced chunk followed by a DONE marker for
        OpenAI‑style streams.
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

    # --------------------------------------------------------------------- #
    # Public streaming entry points
    # --------------------------------------------------------------------- #

    def stream_generic(
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
        Generic (OpenAI‑style) streaming – returns the raw SSE bytes unchanged.
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_generic(force_text, api_model_provider)

        # Ensure we accept an SSE format
        headers["Accept"] = "text/event-stream"

        def _iter() -> Iterator[bytes]:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                try:
                    request_kwargs = {
                        "url": url,
                        "timeout": endpoint.timeout,
                        "stream": True,
                        "headers": headers,
                    }
                    if method == "POST":
                        request_kwargs["json"] = payload
                        req = requests.post(**request_kwargs)
                    else:
                        request_kwargs["params"] = payload
                        req = requests.get(**request_kwargs)

                    with req as r:
                        r.raise_for_status()
                        for chunk in r.iter_content(chunk_size=None):
                            if chunk:
                                yield chunk
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
        Streaming from an Ollama endpoint – converts the stream to Ollama NDJSON.
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
                        resp_ctx = requests.post(
                            url,
                            json=payload,
                            headers=headers,
                            timeout=endpoint.timeout,
                            stream=True,
                        )
                    else:
                        resp_ctx = requests.get(
                            url,
                            params=payload,
                            headers=headers,
                            timeout=endpoint.timeout,
                            stream=True,
                        )
                    with resp_ctx as resp:
                        resp.raise_for_status()
                        for chunk in self._parse_ollama_stream(
                            resp, api_model_provider
                        ):
                            yield chunk
                except requests.RequestException as exc:
                    yield (json.dumps({"error": str(exc)}) + "\n").encode("utf-8")

        return _iter()

    def stream_generic_to_ollama(
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
        Convert an OpenAI‑style stream to Ollama NDJSON.
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

    def stream_ollama_to_generic(
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
        """
        if force_text is not None:
            with self._model_unsetter(
                endpoint, payload, api_model_provider, options
            ):
                return self._force_iter_generic(force_text, api_model_provider)

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

    # --------------------------------------------------------------------- #
    # Stream‑type resolution – moved from EndpointWithHttpRequestI
    # --------------------------------------------------------------------- #

    @staticmethod
    def resolve_stream_type(
        endpoint_ep_types: list, api_model_provider
    ) -> tuple[bool, bool, bool]:
        """
        Determine which streaming conversion should be applied.

        Returns a tuple:
        (is_generic_to_ollama, is_ollama_to_generic, is_ollama)
        """
        is_generic_to_ollama = False
        is_ollama_to_generic = False
        is_ollama = (
            "ollama" in endpoint_ep_types and "ollama" in api_model_provider.api_type
        )
        if not is_ollama:
            if "ollama" in endpoint_ep_types:
                is_generic_to_ollama = True
            if "ollama" in api_model_provider.api_type:
                is_ollama_to_generic = True
        return is_generic_to_ollama, is_ollama_to_generic, is_ollama

    #
    # def _resolve_stream_type(self, api_model_provider: ApiModel) -> Dict[str, bool]:
    #     resolved_stream = {
    #         "is_ollama": False,
    #         "is_lm_studio": False,
    #         "is_lm_studio_to_ollama": False,
    #         "is_generic_to_ollama": False,
    #         "is_generic_to_llmstudio": False,
    #         "is_ollama_to_generic": False,
    #         "is_lmstudio_to_generic": False,
    #         "is_ollama_to_lm_studio": False,
    #     }
    #
    #     # is ollama -> ollama?
    #     if (
    #         "ollama" in self._ep_types_str
    #         and "ollama" in api_model_provider.api_type
    #     ):
    #         resolved_stream["is_ollama"] = True
    #         return resolved_stream
    #
    #     # is lm_studio -> lm_studio?
    #     if (
    #         "lm_studio" in self._ep_types_str
    #         and "lm_studio" in api_model_provider.api_type
    #     ):
    #         resolved_stream["is_lm_studio"] = True
    #         return resolved_stream
    #
    #     # lm_studio -> ollama
    #     if "ollama" in self._ep_types_str and "lm_studio" in api_model_provider:
    #         resolved_stream["is_lm_studio_to_ollama"] = True
    #         return resolved_stream
    #
    #     #
    #     #     if "ollama" in self._ep_types_str:
    #     #         is_generic_to_ollama = True
    #     #
    #     #     if "ollama" in api_model_provider.api_type:
    #     #         is_ollama_to_generic = True
    #     #
    #     # return is_generic_to_ollama, is_ollama_to_generic, is_ollama
    #     return resolved_stream
