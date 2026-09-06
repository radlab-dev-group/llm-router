"""
Unit tests for ``llm_router_api.core.stream_handler.StreamHandler``.

Covers the error-message/status helpers, the forced-text generators, the
Ollama NDJSON chunk builder and stream parser, the stream-type resolver,
and the request-based conversion generators (OpenAI↔Ollama, Anthropic→
OpenAI) with ``requests`` mocked.  No network access is performed.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from types import SimpleNamespace  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

import llm_router_api.core.stream_handler as sh  # noqa: E402
from llm_router_api.core.stream_handler import (  # noqa: E402
    StreamConversion,
    StreamHandler,
    _raise_for_status,
    _request_error_message,
)


def _model(model_path: str = "", name: str = "m-1"):
    return SimpleNamespace(model_path=model_path, name=name)


def _endpoint(timeout=5):
    ep = mock.Mock()
    ep.timeout = timeout
    ep.unset_model = mock.Mock()
    ep.logger = None
    return ep


class _FakeResp:
    """Minimal stand-in for a (streaming) requests.Response."""

    def __init__(self, lines=None, content=None, status_code=200, text=""):
        self._lines = list(lines or [])
        self._content = list(content or [])
        self.status_code = status_code
        self.text = text
        self.reason = "OK"
        self.url = "http://test.local/api"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, decode_unicode=False):
        return iter(self._lines)

    def iter_content(self, chunk_size=None):
        return iter(self._content)


def _consume(gen):
    return list(gen)


class TestRequestErrorMessage:
    def test_no_body_returns_base(self):
        exc = ValueError("boom")
        assert _request_error_message(exc) == "boom"

    def test_provider_body_attribute_used(self):
        exc = ValueError("base")
        exc.provider_body = "provider detail"
        assert "provider: provider detail" in _request_error_message(exc)

    def test_body_from_response_text(self):
        exc = requests.RequestException("base")
        exc.response = SimpleNamespace(text="  from-response  ")
        msg = _request_error_message(exc)
        assert "provider: from-response" in msg

    def test_body_truncated_to_500(self):
        exc = ValueError("base")
        exc.provider_body = "x" * 900
        msg = _request_error_message(exc)
        # base + " — provider: " + 500 chars
        assert msg.endswith("x" * 500)
        assert "x" * 501 not in msg


class TestRaiseForStatus:
    def test_none_response_ok(self):
        _raise_for_status(None)  # no raise

    def test_2xx_and_3xx_ok(self):
        for code in (200, 201, 301, 302):
            _raise_for_status(_FakeResp(status_code=code))

    def test_4xx_raises_with_provider_body(self):
        resp = _FakeResp(status_code=400, text="bad request detail")
        with pytest.raises(requests.HTTPError) as ei:
            _raise_for_status(resp)
        assert ei.value.provider_body == "bad request detail"
        assert "400" in str(ei.value)

    def test_5xx_raises(self):
        resp = _FakeResp(status_code=503, text="unavailable")
        with pytest.raises(requests.HTTPError):
            _raise_for_status(resp)

    def test_provider_body_truncated_to_1000(self):
        resp = _FakeResp(status_code=500, text="y" * 1500)
        with pytest.raises(requests.HTTPError) as ei:
            _raise_for_status(resp)
        assert len(ei.value.provider_body) == 1000


class TestForceIterOpenAI:
    def test_two_chunks_and_done(self):
        gen = StreamHandler._force_iter_openai("hello", _model("mp", "nm"))
        out = _consume(gen)
        assert len(out) == 2
        assert out[1] == b"data: [DONE]\n\n"
        first = json.loads(out[0][5:].decode())
        assert first["model"] == "mp"
        assert first["choices"][0]["delta"]["content"] == "hello"
        assert first["object"] == "chat.completion.chunk"

    def test_model_falls_back_to_name(self):
        gen = StreamHandler._force_iter_openai("x", _model("", "nm"))
        first = json.loads(_consume(gen)[0][5:].decode())
        assert first["model"] == "nm"


class TestForceIterLMStudio:
    def test_three_chunks(self):
        gen = StreamHandler._force_iter_lmstudio("hi", _model("mp", "nm"))
        out = _consume(gen)
        assert len(out) == 3
        assert out[2] == b"data: [DONE]\n\n"
        c1 = json.loads(out[0][5:].decode())
        c2 = json.loads(out[1][5:].decode())
        assert c1["choices"][0]["delta"]["role"] == "assistant"
        assert c1["choices"][0]["delta"]["content"] == "hi"
        assert c2["choices"][0]["finish_reason"] == "stop"


class TestForceIterOllama:
    def test_ndjson_chunks(self):
        handler = StreamHandler()
        gen = handler._force_iter_ollama("txt", _model("mp", "nm"))
        out = _consume(gen)
        assert len(out) == 2
        c1 = json.loads(out[0].decode())
        c2 = json.loads(out[1].decode())
        assert c1["done"] is False
        assert c1["message"]["content"] == "txt"
        assert c2["done"] is True


class TestOllamaChunk:
    def test_not_done(self):
        obj = json.loads(
            StreamHandler._ollama_chunk(
                "abc", done=False, api_model_provider=_model("mp", "nm")
            ).decode()
        )
        assert obj["done"] is False
        assert obj["message"] == {"role": "assistant", "content": "abc"}
        assert obj["model"] == "mp"

    def test_done_with_usage(self):
        obj = json.loads(
            StreamHandler._ollama_chunk(
                "",
                done=True,
                usage={"prompt_tokens": 7, "completion_tokens": 3},
                api_model_provider=_model("", "nm"),
            ).decode()
        )
        assert obj["done"] is True
        assert obj["prompt_eval_count"] == 7
        assert obj["eval_count"] == 3
        assert obj["message"]["content"] == ""


class TestParseOllamaStream:
    def _handler(self):
        return StreamHandler()

    def test_sse_data_lines(self):
        lines = [
            b"data: "
            + json.dumps({"choices": [{"delta": {"content": "foo"}}]}).encode(),
            b"data: [DONE]",
        ]
        out = _consume(
            self._handler()._parse_ollama_stream(
                _FakeResp(lines=lines), _model("mp", "nm")
            )
        )
        parsed = [json.loads(x.decode()) for x in out]
        assert parsed[0]["message"]["content"] == "foo"
        assert parsed[0]["done"] is False
        assert parsed[-1]["done"] is True

    def test_finish_reason_emits_done(self):
        lines = [
            (
                b"data: "
                + json.dumps(
                    {"choices": [{"delta": {"content": "a"}, "finish_reason": None}]}
                ).encode()
            ),
            (
                b"data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {},
                                "finish_reason": "stop",
                                "usage": {
                                    "prompt_tokens": 2,
                                    "completion_tokens": 1,
                                },
                            }
                        ]
                    }
                ).encode()
            ),
        ]
        out = _consume(
            self._handler()._parse_ollama_stream(
                _FakeResp(lines=lines), _model("mp", "nm")
            )
        )
        parsed = [json.loads(x.decode()) for x in out]
        assert any(p["done"] for p in parsed)
        done = [p for p in parsed if p["done"]][-1]
        # no duplicate done chunk beyond the single one emitted
        assert sum(1 for p in parsed if p["done"]) == 1

    def test_non_json_sse_line_passthrough(self):
        lines = [b"data: not-json", b"data: [DONE]"]
        out = _consume(
            self._handler()._parse_ollama_stream(
                _FakeResp(lines=lines), _model("mp", "nm")
            )
        )
        assert b"not-json" in out[0]

    def test_ndjson_done_line(self):
        lines = [
            json.dumps({"message": {"content": "x"}, "done": False}).encode(),
            json.dumps({"done": True}).encode(),
        ]
        out = _consume(
            self._handler()._parse_ollama_stream(
                _FakeResp(lines=lines), _model("mp", "nm")
            )
        )
        parsed = [json.loads(x.decode()) for x in out]
        assert parsed[0]["message"]["content"] == "x"
        assert parsed[-1]["done"] is True

    def test_stream_end_emits_final_done(self):
        lines = [
            (
                b"data: "
                + json.dumps({"choices": [{"delta": {"content": "only"}}]}).encode()
            )
        ]
        out = _consume(
            self._handler()._parse_ollama_stream(
                _FakeResp(lines=lines), _model("mp", "nm")
            )
        )
        parsed = [json.loads(x.decode()) for x in out]
        assert parsed[-1]["done"] is True


class TestResolveStreamType:
    @pytest.mark.parametrize(
        "ep,prov,expected",
        [
            (["ollama"], "ollama", StreamConversion.OLLAMA),
            (["openai"], "openai", StreamConversion.OPENAI),
            (["openai"], "vllm", StreamConversion.OPENAI),
            (["lmstudio"], "lmstudio", StreamConversion.LMSTUDIO_PASSTHROUGH),
            (["anthropic"], "anthropic", StreamConversion.ANTHROPIC),
            (["ollama"], "openai", StreamConversion.OPENAI_TO_OLLAMA),
            (["ollama"], "lmstudio", StreamConversion.OPENAI_TO_OLLAMA),
            (["ollama"], "anthropic", None),
            (["openai"], "ollama", StreamConversion.OLLAMA_TO_OPENAI),
            (["openai"], "anthropic", StreamConversion.ANTHROPIC_TO_OPENAI),
            (["lmstudio"], "openai", StreamConversion.OPENAI_TO_LMSTUDIO),
            (["lmstudio"], "ollama", StreamConversion.OLLAMA_TO_LMSTUDIO),
            (["lmstudio"], "anthropic", None),
        ],
    )
    def test_matrix(self, ep, prov, expected):
        assert (
            StreamHandler.resolve_stream_type(ep, SimpleNamespace(api_type=prov))
            is expected
        )


class _ReqPatch:
    """Helper to patch requests.post/get/request inside the handler module."""

    def __init__(self, monkeypatch, response=None, side_effect=None):
        self.response = response
        self.side_effect = side_effect
        self.post = mock.Mock()
        self.get = mock.Mock()
        self.request = mock.Mock()
        for fn in (self.post, self.get, self.request):
            if side_effect is not None:
                fn.side_effect = side_effect
            else:
                fn.return_value = response
        for name in ("post", "get", "request"):
            monkeypatch.setattr(sh.requests, name, getattr(self, name))


class TestStreamOpenAItoOllama:
    def test_post_uses_json_and_unset_model_once(self, monkeypatch):
        resp = _FakeResp(
            lines=[
                (
                    b"data: "
                    + json.dumps({"choices": [{"delta": {"content": "z"}}]}).encode()
                ),
                b"data: [DONE]",
            ]
        )
        patch = _ReqPatch(monkeypatch, response=resp)
        ep = _endpoint()
        handler = StreamHandler()

        out = _consume(
            handler.stream_openai_to_ollama(
                "http://u", {"a": 1}, "POST", {}, None, ep, _model("mp", "nm")
            )
        )
        assert out
        patch.post.assert_called_once()
        assert patch.post.call_args.kwargs["json"] == {"a": 1}
        ep.unset_model.assert_called_once()

    def test_get_uses_params(self, monkeypatch):
        resp = _FakeResp(lines=[b"data: [DONE]"])
        patch = _ReqPatch(monkeypatch, response=resp)
        handler = StreamHandler()
        _consume(
            handler.stream_openai_to_ollama(
                "http://u", {"q": 2}, "GET", {}, None, _endpoint(), _model()
            )
        )
        assert patch.get.call_args.kwargs["params"] == {"q": 2}

    def test_force_text_branch(self, monkeypatch):
        ep = _endpoint()
        handler = StreamHandler()
        out = _consume(
            handler.stream_openai_to_ollama(
                "http://u",
                {},
                "POST",
                {},
                None,
                ep,
                _model("mp", "nm"),
                force_text="forced",
            )
        )
        parsed = [json.loads(x.decode()) for x in out]
        assert parsed[0]["message"]["content"] == "forced"
        ep.unset_model.assert_called_once()

    def test_request_exception_yields_error(self, monkeypatch):
        exc = requests.RequestException("conn refused")
        patch = _ReqPatch(monkeypatch, side_effect=exc)
        handler = StreamHandler()
        out = _consume(
            handler.stream_openai_to_ollama(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert len(out) == 1
        payload = json.loads(out[0].decode())
        assert "error" in payload


class TestStreamOllamaToOpenAI:
    def test_converts_ndjson_to_sse(self, monkeypatch):
        resp = _FakeResp(
            lines=[
                json.dumps({"message": {"content": "h"}, "done": False}).encode(),
                json.dumps({"done": True}).encode(),
            ]
        )
        patch = _ReqPatch(monkeypatch, response=resp)
        ep = _endpoint()
        handler = StreamHandler()

        out = _consume(
            handler.stream_ollama_to_openai(
                "http://u", {"m": 1}, "POST", {}, None, ep, _model("mp", "nm")
            )
        )
        # content chunk + finish chunk + [DONE]
        assert b"data: [DONE]\n\n" in out
        first = json.loads(out[0][5:].decode())
        assert first["choices"][0]["delta"]["content"] == "h"
        patch.post.assert_called_once()
        ep.unset_model.assert_called_once()

    def test_non_json_line_forwarded(self, monkeypatch):
        resp = _FakeResp(
            lines=[b"garbage-line", json.dumps({"done": True}).encode()]
        )
        _ReqPatch(monkeypatch, response=resp)
        handler = StreamHandler()
        out = _consume(
            handler.stream_ollama_to_openai(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert any(b"garbage-line" in x for x in out)

    def test_request_exception_yields_error(self, monkeypatch):
        exc = requests.RequestException("nope")
        _ReqPatch(monkeypatch, side_effect=exc)
        handler = StreamHandler()
        out = _consume(
            handler.stream_ollama_to_openai(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert len(out) == 1
        assert b'"error"' in out[0]


class TestStreamAnthropicToOpenAI:
    def test_headers_and_conversion(self, monkeypatch):
        lines = [
            b"event: content_block_delta",
            (
                b"data: "
                + json.dumps(
                    {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "hi"},
                    }
                ).encode()
            ),
            b"data: [DONE]",
        ]
        resp = _FakeResp(lines=lines)
        patch = _ReqPatch(monkeypatch, response=resp)
        handler = StreamHandler()
        headers = {}
        out = _consume(
            handler.stream_anthropic_to_openai(
                "http://u", {}, "POST", headers, None, _endpoint(), _model()
            )
        )
        assert headers["Accept"] == "text/event-stream"
        assert headers["anthropic-version"] == "2023-06-01"
        assert b"data: [DONE]\n\n" in out
        content = [
            json.loads(x[5:].decode()) for x in out if x.startswith(b"data: {")
        ]
        assert content[0]["choices"][0]["delta"]["content"] == "hi"
        patch.request.assert_called_once()

    def test_request_exception_yields_error(self, monkeypatch):
        exc = requests.RequestException("down")
        _ReqPatch(monkeypatch, side_effect=exc)
        handler = StreamHandler()
        out = _consume(
            handler.stream_anthropic_to_openai(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert len(out) == 1
        assert b'"error"' in out[0]


class TestPassthroughGenerator:
    def test_stream_openai_passthrough(self, monkeypatch):
        resp = _FakeResp(content=[b"chunk-1", b"chunk-2"])
        patch = _ReqPatch(monkeypatch, response=resp)
        ep = _endpoint()
        handler = StreamHandler()
        out = _consume(
            handler.stream_openai(
                "http://u", {"s": 1}, "POST", {}, None, ep, _model()
            )
        )
        assert out == [b"chunk-1", b"chunk-2"]
        ep.unset_model.assert_called_once()

    def test_stream_anthropic_sets_headers(self, monkeypatch):
        resp = _FakeResp(content=[b"x"])
        _ReqPatch(monkeypatch, response=resp)
        handler = StreamHandler()
        headers = {}
        _consume(
            handler.stream_anthropic(
                "http://u", {}, "POST", headers, None, _endpoint(), _model()
            )
        )
        assert headers["anthropic-version"] == "2023-06-01"
        assert headers["Accept"] == "text/event-stream"


class TestStreamOpenAitoLMStudio:
    def test_normalizes_sse_to_lmstudio_shape(self, monkeypatch):
        first = {
            "id": "abc-1",
            "created": 123,
            "model": "gpt-x",
            "object": "chat.completion.chunk",
            "choices": [
                {"index": 0, "delta": {"content": "he"}, "finish_reason": None}
            ],
        }
        second = {
            "id": "abc-1",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        resp = _FakeResp(
            lines=[
                b"data: " + json.dumps(first).encode(),
                b"data: " + json.dumps(second).encode(),
                b"data: [DONE]",
            ]
        )
        _ReqPatch(monkeypatch, response=resp)
        ep = _endpoint()
        headers = {}
        out = _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u", {"p": 1}, "POST", headers, None, ep, _model("mp", "nm")
            )
        )
        # request headers are normalised for SSE
        assert headers["Accept"] == "text/event-stream"
        assert headers["Cache-Control"] == "no-cache"
        assert headers["Connection"] == "keep-alive"

        def _sse_obj(chunk: bytes):
            text = chunk.decode()
            assert text.startswith("data: ")
            return json.loads(text[6:].strip())

        first_obj = _sse_obj(out[0])
        second_obj = _sse_obj(out[1])
        # stable metadata is captured from the first parsable chunk
        assert first_obj["id"] == "abc-1"
        assert first_obj["created"] == 123
        assert first_obj["model"] == "gpt-x"
        assert first_obj["system_fingerprint"] == "mp"
        # LM Studio expects a role on the first emitted delta
        assert first_obj["choices"][0]["delta"] == {
            "role": "assistant",
            "content": "he",
        }
        # role is not re-sent afterwards
        assert second_obj["choices"][0]["delta"] == {}
        assert second_obj["choices"][0]["finish_reason"] == "stop"
        assert out[2] == b"data: [DONE]\n\n"
        ep.unset_model.assert_called_once()

    def test_delta_restricted_to_role_and_content(self, monkeypatch):
        event = {
            "id": "i-1",
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [1], "role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
        resp = _FakeResp(lines=[b"data: " + json.dumps(event).encode()])
        _ReqPatch(monkeypatch, response=resp)
        out = _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u", {}, "POST", {}, None, _endpoint(), _model("", "nm")
            )
        )
        obj = json.loads(out[0].decode()[6:].strip())
        # tool_calls are stripped; only role/content survive
        assert obj["choices"][0]["delta"] == {"role": "assistant"}
        # model_path empty -> name is used
        assert obj["model"] == "nm"

    def test_non_data_line_and_bad_json_passthrough(self, monkeypatch):
        resp = _FakeResp(
            lines=[
                b"event: something",
                b"data: {not-json",
                b"data: [DONE]",
            ]
        )
        _ReqPatch(monkeypatch, response=resp)
        out = _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u", {}, "GET", {}, None, _endpoint(), _model()
            )
        )
        assert out[0] == b"data: event: something\n\n"
        assert out[1] == b"data: {not-json\n\n"
        assert out[2] == b"data: [DONE]\n\n"

    def test_empty_and_non_dict_choices_get_default_chunk(self, monkeypatch):
        resp = _FakeResp(
            lines=[
                b"data: " + json.dumps({"id": "i-1", "choices": []}).encode(),
                b"data: " + json.dumps({"choices": [42]}).encode(),
            ]
        )
        _ReqPatch(monkeypatch, response=resp)
        out = _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        first = json.loads(out[0].decode()[6:].strip())
        second = json.loads(out[1].decode()[6:].strip())
        # the empty-choices fallback keeps an empty delta
        assert first["choices"][0]["delta"] == {}
        # the invalid-choices fallback injects the role (not sent yet)
        assert second["choices"][0]["delta"] == {"role": "assistant"}

    def test_get_uses_params(self, monkeypatch):
        resp = _FakeResp(lines=[b"data: [DONE]"])
        patch = _ReqPatch(monkeypatch, response=resp)
        _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u", {"q": 1}, "GET", {}, None, _endpoint(), _model()
            )
        )
        assert patch.get.call_args.kwargs["params"] == {"q": 1}

    def test_force_text_branch(self, monkeypatch):
        ep = _endpoint()
        out = _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u",
                {},
                "POST",
                {},
                None,
                ep,
                _model("mp", "nm"),
                force_text="forced",
            )
        )
        # force-text reuses the OpenAI-shaped generator
        assert any(b"forced" in x for x in out)
        ep.unset_model.assert_called_once()

    def test_request_exception_yields_error(self, monkeypatch):
        _ReqPatch(monkeypatch, side_effect=requests.RequestException("down"))
        out = _consume(
            StreamHandler().stream_openai_to_lmstudio(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert len(out) == 1
        assert b'"error"' in out[0]


class TestStreamOllamaToLMStudio:
    def test_converts_ndjson_to_lmstudio_sse(self, monkeypatch):
        resp = _FakeResp(
            lines=[
                json.dumps({"message": {"content": "He"}, "done": False}).encode(),
                json.dumps({"message": {"content": "llo"}, "done": False}).encode(),
                json.dumps({"done": True}).encode(),
            ]
        )
        _ReqPatch(monkeypatch, response=resp)
        ep = _endpoint()
        out = _consume(
            StreamHandler().stream_ollama_to_lmstudio(
                "http://u", {"m": 1}, "POST", {}, None, ep, _model("mp", "nm")
            )
        )
        # two content events + finish event + [DONE]
        assert len(out) == 4
        first = json.loads(out[0][5:].decode())
        assert first["id"].startswith("chatcmpl-")
        assert first["object"] == "chat.completion.chunk"
        assert first["system_fingerprint"] == "mp"
        assert first["choices"][0]["delta"] == {"role": "assistant", "content": "He"}
        second = json.loads(out[1][5:].decode())
        # role is not repeated on subsequent chunks
        assert second["choices"][0]["delta"] == {"content": "llo"}
        finish = json.loads(out[2][5:].decode())
        assert finish["choices"][0]["finish_reason"] == "stop"
        assert out[3] == b"data: [DONE]\n\n"
        ep.unset_model.assert_called_once()

    def test_empty_content_is_skipped(self, monkeypatch):
        resp = _FakeResp(
            lines=[
                json.dumps({"message": {"content": ""}, "done": False}).encode(),
                json.dumps({"done": True}).encode(),
            ]
        )
        _ReqPatch(monkeypatch, response=resp)
        out = _consume(
            StreamHandler().stream_ollama_to_lmstudio(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        # only the finish event and [DONE] are emitted
        assert len(out) == 2
        assert out[1] == b"data: [DONE]\n\n"

    def test_non_json_line_forwarded(self, monkeypatch):
        resp = _FakeResp(
            lines=[b"garbage-line", json.dumps({"done": True}).encode()]
        )
        _ReqPatch(monkeypatch, response=resp)
        out = _consume(
            StreamHandler().stream_ollama_to_lmstudio(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert any(b"garbage-line" in x for x in out)

    def test_get_uses_params(self, monkeypatch):
        resp = _FakeResp(lines=[json.dumps({"done": True}).encode()])
        patch = _ReqPatch(monkeypatch, response=resp)
        _consume(
            StreamHandler().stream_ollama_to_lmstudio(
                "http://u", {"q": 2}, "GET", {}, None, _endpoint(), _model()
            )
        )
        assert patch.get.call_args.kwargs["params"] == {"q": 2}

    def test_force_text_branch(self, monkeypatch):
        ep = _endpoint()
        out = _consume(
            StreamHandler().stream_ollama_to_lmstudio(
                "http://u",
                {},
                "POST",
                {},
                None,
                ep,
                _model("mp", "nm"),
                force_text="forced",
            )
        )
        assert any(b"forced" in x for x in out)
        ep.unset_model.assert_called_once()

    def test_request_exception_yields_error(self, monkeypatch):
        _ReqPatch(monkeypatch, side_effect=requests.RequestException("nope"))
        out = _consume(
            StreamHandler().stream_ollama_to_lmstudio(
                "http://u", {}, "POST", {}, None, _endpoint(), _model()
            )
        )
        assert len(out) == 1
        assert b'"error"' in out[0]


class TestLogRequestError:
    def test_no_logger_is_noop(self):
        ep = _endpoint()
        ep.logger = None
        # must not raise
        StreamHandler._log_request_error(ep, ValueError("boom"))

    def test_logs_status_when_available(self):
        ep = _endpoint()
        ep.logger = mock.Mock()
        exc = requests.RequestException("bad")
        exc.response = mock.Mock(status_code=503, text="upstream says no")
        StreamHandler._log_request_error(ep, exc)
        ep.logger.error.assert_called_once()
        args = ep.logger.error.call_args[0]
        assert "HTTP %s" in args[0]
        assert 503 in args[1:]

    def test_logs_message_without_status(self):
        ep = _endpoint()
        ep.logger = mock.Mock()
        StreamHandler._log_request_error(ep, ValueError("boom"))
        ep.logger.error.assert_called_once()
        args = ep.logger.error.call_args[0]
        assert "boom" in args[1:]


class TestForceTextEntryPoints:
    def test_stream_openai_force_text(self, monkeypatch):
        ep = _endpoint()
        out = _consume(
            StreamHandler().stream_openai(
                "http://u",
                {},
                "POST",
                {},
                None,
                ep,
                _model("mp", "nm"),
                force_text="hi there",
            )
        )
        assert any(b"hi there" in x for x in out)
        ep.unset_model.assert_called_once()

    def test_stream_ollama_force_text(self, monkeypatch):
        ep = _endpoint()
        out = _consume(
            StreamHandler().stream_ollama(
                "http://u",
                {},
                "POST",
                {},
                None,
                ep,
                _model("mp", "nm"),
                force_text="hi there",
            )
        )
        # Ollama-shaped NDJSON force-text chunk
        first = json.loads(out[0].decode())
        assert first["message"]["content"] == "hi there"
        ep.unset_model.assert_called_once()


class TestStreamOpenAitoAnthropic:
    def test_sets_accept_and_passthrough(self, monkeypatch):
        resp = _FakeResp(content=[b"pass-1"])
        patch = _ReqPatch(monkeypatch, response=resp)
        headers = {}
        ep = _endpoint()
        out = _consume(
            StreamHandler().stream_openai_to_anthropic(
                "http://u", {"s": 1}, "POST", headers, None, ep, _model()
            )
        )
        assert headers["Accept"] == "text/event-stream"
        assert out == [b"pass-1"]
        assert patch.post.call_args.kwargs["json"] == {"s": 1}
        ep.unset_model.assert_called_once()
