"""
Tests for ``llm_router_cli.util.json_utils`` — the shared helpers that
parse JSON answers returned by LLMs (including answers wrapped in a
markdown code fence).
"""

from __future__ import annotations

import json

import pytest

from llm_router_cli.util.json_utils import loads_json, strip_code_fence


# ---------------------------------------------------------------------- #
# strip_code_fence
# ---------------------------------------------------------------------- #


def test_no_fence_returns_text_unchanged() -> None:
    text = '{"a": 1}'
    assert strip_code_fence(text) == text


def test_no_fence_keeps_surrounding_whitespace() -> None:
    # Without a leading fence the original text is returned as-is.
    assert strip_code_fence('  {"a": 1}  ') == '  {"a": 1}  '


def test_json_fenced_block_is_stripped() -> None:
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_plain_fenced_block_is_stripped() -> None:
    assert strip_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'


def test_fence_without_trailing_marker() -> None:
    assert strip_code_fence('```json\n{"a": 1}') == '{"a": 1}'


def test_fence_with_leading_whitespace() -> None:
    assert strip_code_fence("   ```json\n[1, 2]\n```   ") == "[1, 2]"


def test_empty_fence_yields_empty_string() -> None:
    assert strip_code_fence("```") == ""
    assert strip_code_fence("```json") == ""


def test_fence_around_multiline_json() -> None:
    payload = '{"a": [1, 2],\n "b": {"c": 3}}'
    assert strip_code_fence(f"```json\n{payload}\n```") == payload


# ---------------------------------------------------------------------- #
# loads_json
# ---------------------------------------------------------------------- #


def test_loads_json_plain_object() -> None:
    assert loads_json('{"a": [1, 2]}') == {"a": [1, 2]}


def test_loads_json_plain_list() -> None:
    assert loads_json("[1, 2, 3]") == [1, 2, 3]


def test_loads_json_fenced() -> None:
    assert loads_json('```json\n{"exists": true, "class": "x"}\n```') == {
        "exists": True,
        "class": "x",
    }


def test_loads_json_invalid_raises_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_json("this is not json")


def test_loads_json_fenced_invalid_raises_decode_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_json("```json\n{oops\n```")
