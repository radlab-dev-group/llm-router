"""
Utilities for handling streaming HTTP responses.

The functions mirror the original private helpers that lived inside
`HttpRequestExecutor`.  They receive the owning ``endpoint`` instance so
that they can use its timeout, logger and ``unset_model`` hook.
"""

import json
import datetime
import contextlib
from typing import Iterator, Dict, Any, Optional

import requests
from requests import Response

# --------------------------------------------------------------------------- #
# Internal utilities – extracted to avoid repetition
# --------------------------------------------------------------------------- #


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


def _force_iter_generic(force_text: str, api_model_provider) -> Iterator[bytes]:
    """
    Generates a single forced chunk followed by a DONE marker for
    OpenAI‑style streams.
    """
    base_chunk = {
        "id": "chatcmpl-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S"),
        "object": "chat.completion.chunk",
        "created": int(datetime.datetime.utcnow().timestamp()),
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


def _force_iter_ollama(force_text: str, api_model_provider) -> Iterator[bytes]:
    """
    Generates forced chunks for Ollama‑style NDJSON streams.
    """

    def _iter() -> Iterator[bytes]:
        yield _ollama_chunk(
            delta=force_text, done=False, api_model_provider=api_model_provider
        )
        yield _ollama_chunk(
            delta="", done=True, api_model_provider=api_model_provider
        )

    return _iter()


# --------------------------------------------------------------------------- #
# Public streaming entry points
# --------------------------------------------------------------------------- #


def stream_generic(
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
        with _model_unsetter(endpoint, payload, api_model_provider, options):
            return _force_iter_generic(force_text, api_model_provider)

    # Ensure we accept SSE format
    headers["Accept"] = "text/event-stream"

    def _iter() -> Iterator[bytes]:
        with _model_unsetter(endpoint, payload, api_model_provider, options):
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
                yield (f"data: {json.dumps(err)}\n\n").encode("utf-8")

    return _iter()


def stream_ollama(
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
        with _model_unsetter(endpoint, payload, api_model_provider, options):
            return _force_iter_ollama(force_text, api_model_provider)

    def _iter() -> Iterator[bytes]:
        with _model_unsetter(endpoint, payload, api_model_provider, options):
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
                    for chunk in _parse_ollama_stream(resp, api_model_provider):
                        yield chunk
            except requests.RequestException as exc:
                yield (json.dumps({"error": str(exc)}) + "\n").encode("utf-8")

    return _iter()


def stream_generic_to_ollama(
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
        with _model_unsetter(endpoint, payload, api_model_provider, options):
            return _force_iter_ollama(force_text, api_model_provider)

    def _iter() -> Iterator[bytes]:
        with _model_unsetter(endpoint, payload, api_model_provider, options):
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
                    # Re‑use the existing robust parser for Ollama NDJSON
                    for chunk in _parse_ollama_stream(resp, api_model_provider):
                        yield chunk
            except requests.RequestException as exc:
                err = {"error": str(exc)}
                yield (json.dumps(err) + "\n").encode("utf-8")

    return _iter()


def stream_ollama_to_generic(
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
        with _model_unsetter(endpoint, payload, api_model_provider, options):
            return _force_iter_generic(force_text, api_model_provider)

    def _iter() -> Iterator[bytes]:
        with _model_unsetter(endpoint, payload, api_model_provider, options):
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
                            "created": int(datetime.datetime.utcnow().timestamp()),
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

                        delta_text = ollama_obj.get("message", {}).get("content", "")
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


# --------------------------------------------------------------------------- #
# Helper utilities (kept private to this module)
# --------------------------------------------------------------------------- #


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


def _parse_ollama_stream(response: Response, api_model_provider) -> Iterator[bytes]:
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
                    yield _ollama_chunk(
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
                delta_obj = choices[0].get("delta") or choices[0].get("text") or {}
                if isinstance(delta_obj, dict):
                    delta_text = delta_obj.get("content") or ""
                elif isinstance(delta_obj, str):
                    delta_text = delta_obj

            if delta_text:
                yield _ollama_chunk(
                    delta=delta_text,
                    done=False,
                    api_model_provider=api_model_provider,
                )

            # Final chunk on finish_reason
            if choices and choices[0].get("finish_reason") and not sent_done:
                yield _ollama_chunk(
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
                yield _ollama_chunk(
                    delta=delta_text,
                    done=False,
                    api_model_provider=api_model_provider,
                )
            if ch and ch[0].get("finish_reason") and not sent_done:
                yield _ollama_chunk(
                    delta="",
                    done=True,
                    usage=usage_data,
                    api_model_provider=api_model_provider,
                )
                sent_done = True
        elif evt.get("done") is True and not sent_done:
            yield _ollama_chunk(
                delta="",
                done=True,
                usage=usage_data,
                api_model_provider=api_model_provider,
            )
            sent_done = True
        else:
            yield (line + "\n").encode("utf-8")

    if not sent_done:
        yield _ollama_chunk(
            delta="",
            done=True,
            usage=usage_data,
            api_model_provider=api_model_provider,
        )
