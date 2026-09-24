"""
Unit tests for streaming support:

* :func:`llm_router_lib.utils.stream.parse_stream_line` — normalisation of
  OpenAI SSE chunks, Ollama NDJSON chunks, SSE framing, error chunks and
  non-JSON lines;
* :class:`~llm_router_lib.async_client.AsyncLLMRouterClient` streaming
  methods end-to-end over an ``httpx.MockTransport`` (no network).

The async tests require the ``pytest-asyncio`` plugin; the module is skipped
gracefully when the plugin is not installed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx
import pytest

pytest.importorskip("pytest_asyncio")

from llm_router_lib import AsyncLLMRouterClient
from llm_router_lib.data_models.response import StreamEvent
from llm_router_lib.exceptions import LLMRouterError
from llm_router_lib.utils.stream import iter_events, parse_stream_line


# ---------------------------------------------------------------------- #
# parse_stream_line
# ---------------------------------------------------------------------- #
def test_openai_sse_delta_line() -> None:
    event = parse_stream_line(
        'data: {"choices": [{"delta": {"content": "He"}}]}'
    )
    assert event is not None
    assert event.text == "He"
    assert event.done is False
    assert event.raw["choices"][0]["delta"]["content"] == "He"


def test_openai_sse_role_only_line_is_skipped() -> None:
    assert (
        parse_stream_line(
            'data: {"choices": [{"delta": {"role": "assistant"}}]}'
        )
        is None
    )


def test_openai_sse_finish_reason_marks_done() -> None:
    event = parse_stream_line(
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}'
    )
    assert event is not None
    assert event.done is True
    assert event.text == ""


def test_openai_completion_text_fallback() -> None:
    event = parse_stream_line(
        'data: {"choices": [{"text": "abc", "finish_reason": null}]}'
    )
    assert event is not None
    assert event.text == "abc"


def test_openai_empty_choices_list_is_skipped() -> None:
    assert parse_stream_line('data: {"choices": []}') is None


def test_ollama_ndjson_line() -> None:
    event = parse_stream_line('{"response": "Cio", "done": false}')
    assert event is not None
    assert event.text == "Cio"
    assert event.done is False


def test_ollama_final_done_chunk() -> None:
    event = parse_stream_line('{"response": "", "done": true}')
    assert event is not None
    assert event.done is True
    assert event.text == ""


def test_ollama_chat_message_content_fallback() -> None:
    event = parse_stream_line('{"message": {"role": "assistant", "content": "hi"}}')
    assert event is not None
    assert event.text == "hi"


def test_sse_done_marker_is_skipped() -> None:
    assert parse_stream_line("data: [DONE]") is None


def test_sse_comments_and_field_lines_are_skipped() -> None:
    assert parse_stream_line(": keep-alive") is None
    assert parse_stream_line("event: message") is None
    assert parse_stream_line("id: 42") is None
    assert parse_stream_line("retry: 3000") is None


def test_empty_lines_are_skipped() -> None:
    assert parse_stream_line("") is None
    assert parse_stream_line("   ") is None
    assert parse_stream_line("data:") is None


def test_error_chunk_string_raises_llm_router_error() -> None:
    with pytest.raises(LLMRouterError) as ctx:
        parse_stream_line('data: {"error": "boom"}')
    assert "boom" in str(ctx.value)


def test_error_chunk_dict_is_serialised_into_message() -> None:
    with pytest.raises(LLMRouterError) as ctx:
        parse_stream_line('data: {"error": {"message": "inner"}}')
    assert "inner" in str(ctx.value)


def test_non_json_line_passes_through_as_text() -> None:
    event = parse_stream_line("plain text delta")
    assert event is not None
    assert event.text == "plain text delta"
    assert event.raw == {}


def test_non_dict_json_values_are_skipped() -> None:
    assert parse_stream_line("[1, 2]") is None
    assert parse_stream_line("null") is None
    assert parse_stream_line("42") is None


def test_data_prefix_with_extra_spaces() -> None:
    event = parse_stream_line("data:    {\"response\": \"x\", \"done\": false}")
    assert event is not None
    assert event.text == "x"


# ---------------------------------------------------------------------- #
# iter_events over a raw response
# ---------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_iter_events_yields_meaningful_events_only() -> None:
    body = (
        b'data: {"choices": [{"delta": {"role": "assistant"}}]}\n'
        b'\n'
        b'data: {"choices": [{"delta": {"content": "A"}}]}\n'
        b"\n"
        b"data: [DONE]\n"
        b"\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        async def agen():
            yield body

        return httpx.Response(
            200,
            content=agen(),
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        async with client.stream("POST", "http://r.test/api/x") as resp:
            events = [ev async for ev in iter_events(resp)]
    finally:
        await client.aclose()

    assert [ev.text for ev in events] == ["A"]


# ---------------------------------------------------------------------- #
# AsyncLLMRouterClient streaming methods
# ---------------------------------------------------------------------- #
def _sse_client(body: bytes) -> AsyncLLMRouterClient:
    """Build an async client whose endpoints stream *body*."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_aiter(body),
            headers={"content-type": "text/event-stream"},
        )

    return AsyncLLMRouterClient(
        api="http://r.test",
        transport=httpx.MockTransport(handler),
    )


def _aiter(data: bytes) -> Any:
    async def agen():
        yield data

    return agen()


OPENAI_BODY = (
    b'data: {"choices": [{"delta": {"role": "assistant"}}]}\n\n'
    b'data: {"choices": [{"delta": {"content": "He"}}]}\n\n'
    b'data: {"choices": [{"delta": {"content": "llo"}}]}\n\n'
    b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n'
    b"data: [DONE]\n\n"
)

OLLAMA_BODY = (
    b'{"response": "He", "done": false}\n'
    b'{"response": "llo", "done": false}\n'
    b'{"response": "", "done": true}\n'
)


@pytest.mark.asyncio
async def test_stream_conversation_yields_openai_events() -> None:
    captured: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "body": json.loads(request.content),
                "auth": request.headers.get("Authorization"),
            }
        )
        return httpx.Response(
            200,
            content=_aiter(OPENAI_BODY),
            headers={"content-type": "text/event-stream"},
        )

    async with AsyncLLMRouterClient(
        api="http://r.test",
        token="sekret",
        transport=httpx.MockTransport(handler),
    ) as client:
        events = [
            ev
            async for ev in client.stream_conversation_with_model(
                user_last_statement="Hi!", model="gemma"
            )
        ]

    assert [ev.text for ev in events] == ["He", "llo"]
    assert events[-1].done is True
    # stream flag is injected into the wire payload
    assert captured[0]["path"] == "/api/conversation_with_model"
    assert captured[0]["body"]["stream"] is True
    assert captured[0]["body"]["model_name"] == "gemma"
    assert captured[0]["auth"] == "Bearer sekret"


@pytest.mark.asyncio
async def test_stream_conversation_ollama_ndjson() -> None:
    async with _sse_client(OLLAMA_BODY) as client:
        events = [
            ev
            async for ev in client.stream_conversation_with_model(
                user_last_statement="Hi!", model="ollama-model"
            )
        ]

    assert [ev.text for ev in events] == ["He", "llo"]
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_stream_extended_conversation_sends_system_prompt() -> None:
    captured: List[Dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=_aiter(OPENAI_BODY))

    async with AsyncLLMRouterClient(
        api="http://r.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        events = [
            ev
            async for ev in client.stream_extended_conversation_with_model(
                user_last_statement="Hi!",
                system_prompt="Be brief.",
                model="gemma",
            )
        ]

    assert [ev.text for ev in events] == ["He", "llo"]
    assert captured[0]["stream"] is True
    assert captured[0]["system_prompt"] == "Be brief."
    assert captured[0]["model_name"] == "gemma"


@pytest.mark.asyncio
async def test_stream_error_chunk_raises_llm_router_error() -> None:
    body = b'data: {"error": "provider exploded"}\n\n'
    async with _sse_client(body) as client:
        with pytest.raises(LLMRouterError) as ctx:
            async for _ in client.stream_conversation_with_model(
                user_last_statement="Hi!", model="gemma"
            ):
                pass
    assert "provider exploded" in str(ctx.value)


@pytest.mark.asyncio
async def test_collect_stream_text_aggregates_deltas() -> None:
    async with _sse_client(OPENAI_BODY) as client:
        text = await client.collect_stream_text(
            client.stream_conversation_with_model(
                user_last_statement="Hi!", model="gemma"
            )
        )
    assert text == "Hello"


@pytest.mark.asyncio
async def test_early_break_closes_stream_cleanly() -> None:
    async with _sse_client(OPENAI_BODY) as client:
        events = []
        async for ev in client.stream_conversation_with_model(
            user_last_statement="Hi!", model="gemma"
        ):
            events.append(ev)
            if len(events) == 1:
                break
        assert [ev.text for ev in events] == ["He"]
    # generator fully finalised; client still usable afterwards
    async with _sse_client(OPENAI_BODY) as client2:
        text = await client2.collect_stream_text(
            client2.stream_conversation_with_model(
                user_last_statement="Hi!", model="gemma"
            )
        )
    assert text == "Hello"


@pytest.mark.asyncio
async def test_stream_http_error_status_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    async with AsyncLLMRouterClient(
        api="http://r.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(LLMRouterError) as ctx:
            async for _ in client.stream_conversation_with_model(
                user_last_statement="Hi!", model="gemma"
            ):
                pass
    assert "500" in str(ctx.value)


@pytest.mark.asyncio
async def test_stream_401_raises_authentication_error() -> None:
    from llm_router_lib.exceptions import AuthenticationError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="nope")

    async with AsyncLLMRouterClient(
        api="http://r.test",
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(AuthenticationError):
            async for _ in client.stream_conversation_with_model(
                user_last_statement="Hi!", model="gemma"
            ):
                pass
