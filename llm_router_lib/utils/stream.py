"""
Normalisation of streaming (SSE) responses from the router.

The router forwards provider streams as‑is (passthrough): depending on the
downstream provider, a builtin endpoint may emit OpenAI‑compatible SSE chunks
(``data: {"choices": [{"delta": {"content": ...}}]}``), Ollama NDJSON chunks
(``{"response": "...", "done": false}``), or an error chunk
(``data: {"error": "..."}``).  The helpers in this module turn every one of
those wire formats into a single, typed
:class:`~llm_router_lib.data_models.response.StreamEvent`
stream so that callers do not need to know the provider details:

* :func:`parse_stream_line` – converts a single raw line into a
  :class:`StreamEvent` (or ``None`` for bookkeeping lines such as ``[DONE]``),
  raising :class:`~llm_router_lib.exceptions.LLMRouterError` for error chunks;
* :func:`iter_events` – async iterator over an open
  :class:`httpx.Response` that yields only the meaningful events.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from llm_router_lib.data_models.response import StreamEvent
from llm_router_lib.exceptions import LLMRouterError

# SSE framing markers used by the router's stream handler.
_DATA_PREFIX = "data:"
_DONE_MARKER = "[DONE]"
# SSE field lines that never carry payload content.
_IGNORED_PREFIXES = ("event:", "id:", "retry:")


def _sse_payload(line: str) -> Optional[str]:
    """
    Reduce a raw stream line to its JSON payload.

    Handles both wire formats produced by the router:

    * Server‑Sent‑Events – lines prefixed with ``data:`` (the terminal
      ``data: [DONE]`` marker yields ``None``);
    * bare NDJSON – the whole line is the payload (Ollama passthrough).

    Empty lines, SSE comments (``:…``) and the bookkeeping fields
    ``event:`` / ``id:`` / ``retry:`` yield ``None``.
    """
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith(":"):
        return None
    if stripped.startswith(_IGNORED_PREFIXES):
        return None
    if stripped.startswith(_DATA_PREFIX):
        payload = stripped[len(_DATA_PREFIX) :].lstrip()
        if payload == _DONE_MARKER:
            return None
        return payload
    return stripped


def _extract_text(chunk: Dict[str, Any]) -> str:
    """
    Extract the text delta from a single parsed chunk.

    Supports the OpenAI‑compatible shape (``choices[0].delta.content``,
    with ``choices[0].text`` as a fallback) and the Ollama shape
    (``response``, with the chat ``message.content`` as a fallback).
    """
    choices = chunk.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict):
            delta = choice.get("delta")
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    return content
            text = choice.get("text")
            if isinstance(text, str):
                return text
            return ""

    response = chunk.get("response")
    if isinstance(response, str):
        return response

    message = chunk.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content

    return ""


def _is_done(chunk: Dict[str, Any]) -> bool:
    """Return ``True`` when the chunk marks the end of the generation."""
    choices = chunk.get("choices")
    if isinstance(choices, list) and choices:
        choice = choices[0]
        if isinstance(choice, dict) and choice.get("finish_reason") is not None:
            return True
    return bool(chunk.get("done"))


def parse_stream_line(line: str) -> Optional[StreamEvent]:
    """
    Convert one raw stream line into a normalised :class:`StreamEvent`.

    Parameters
    ----------
    line : str
        A single line of the streamed body (SSE ``data: …`` line, NDJSON line,
        SSE comment or empty line).

    Returns
    -------
    Optional[StreamEvent]
        The parsed event, or ``None`` when the line carries no payload
        (empty line, SSE comment, ``[DONE]`` marker, bookkeeping field,
        or a chunk with no text and no ``done`` flag).

    Raises
    ------
    LLMRouterError
        When the line is a JSON error chunk (``{"error": ...}``).
    """
    payload = _sse_payload(line)
    if payload is None:
        return None

    try:
        chunk = json.loads(payload)
    except ValueError:
        # Not JSON – pass the raw text through (tolerant fallback for
        # providers that emit plain‑text deltas).
        if not payload:
            return None
        return StreamEvent(text=payload, raw={})

    if not isinstance(chunk, dict):
        return None

    if "error" in chunk:
        error = chunk["error"]
        message = error if isinstance(error, str) else json.dumps(error)
        raise LLMRouterError(f"Stream error from router: {message}")

    text = _extract_text(chunk)
    done = _is_done(chunk)
    if not text and not done:
        return None
    return StreamEvent(text=text, raw=chunk, done=done)


async def iter_events(
    response: httpx.Response,
    logger: Optional[logging.Logger] = None,
) -> AsyncIterator[StreamEvent]:
    """
    Iterate over the meaningful events of an open streaming response.

    Parameters
    ----------
    response : httpx.Response
        An open, successful streaming response (as yielded by
        :meth:`llm_router_lib.utils.http_async.AsyncHttpRequester.stream`).
    logger : Optional[logging.Logger]
        Optional logger; parse failures are logged at ``debug`` level.

    Yields
    ------
    StreamEvent
        One event per content‑bearing chunk (see
        :func:`parse_stream_line`).

    Raises
    ------
    LLMRouterError
        When the stream contains an error chunk.
    """
    async for line in response.aiter_lines():
        try:
            event = parse_stream_line(line)
        except LLMRouterError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            if logger:
                logger.debug("Skipping unparseable stream line %r: %s", line, exc)
            continue
        if event is not None:
            yield event
