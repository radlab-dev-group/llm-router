"""
Tests for ``llm_router_cli.util.loaders`` — the dependency-free dataset
readers (JSON single-document and JSONL line-oriented) used by the util apps.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_router_cli.util.loaders import (
    _infer_dataset_type,
    _read_json,
    _read_jsonl,
    read_records,
)


# ---------------------------------------------------------------------- #
# _infer_dataset_type
# ---------------------------------------------------------------------- #


def test_infer_jsonl() -> None:
    assert _infer_dataset_type(Path("data.jsonl")) == "jsonl"


def test_infer_json() -> None:
    assert _infer_dataset_type(Path("data.json")) == "json"


def test_infer_is_case_insensitive() -> None:
    assert _infer_dataset_type(Path("DATA.JSONL")) == "jsonl"
    assert _infer_dataset_type(Path("DATA.Json")) == "json"


def test_infer_unknown_extension_raises() -> None:
    with pytest.raises(ValueError, match="Cannot infer dataset type"):
        _infer_dataset_type(Path("data.csv"))


# ---------------------------------------------------------------------- #
# _read_jsonl
# ---------------------------------------------------------------------- #


def test_read_jsonl_basic_records(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    assert _read_jsonl(p) == [{"a": 1}, {"b": 2}]


def test_read_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('\n{"a": 1}\n\n   \n{"b": 2}\n', encoding="utf-8")
    assert _read_jsonl(p) == [{"a": 1}, {"b": 2}]


def test_read_jsonl_skips_invalid_lines_with_warning(tmp_path: Path, caplog) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('{"ok": 1}\n{not json}\n{"also": 2}\n', encoding="utf-8")
    import logging

    with caplog.at_level(logging.WARNING):
        records = _read_jsonl(p)
    assert records == [{"ok": 1}, {"also": 2}]
    assert any("line 2" in r.getMessage() for r in caplog.records)


def test_read_jsonl_skips_non_object_lines(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('42\n"bare string"\n{"kept": true}\n', encoding="utf-8")
    assert _read_jsonl(p) == [{"kept": True}]


def test_read_jsonl_expands_array_lines(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('[{"a": 1}, "skip-me", {"b": 2}]\n{"c": 3}\n', encoding="utf-8")
    assert _read_jsonl(p) == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_read_jsonl_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text("", encoding="utf-8")
    assert _read_jsonl(p) == []


# ---------------------------------------------------------------------- #
# _read_json
# ---------------------------------------------------------------------- #


def test_read_json_top_level_object(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    assert _read_json(p) == [{"a": 1}]


def test_read_json_top_level_array_keeps_objects_only(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    p.write_text('[{"a": 1}, 42, "nope", {"b": 2}]', encoding="utf-8")
    assert _read_json(p) == [{"a": 1}, {"b": 2}]


def test_read_json_top_level_scalar_raises(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    p.write_text("42", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported top-level JSON type"):
        _read_json(p)


def test_read_json_invalid_document_raises(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    p.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        _read_json(p)


# ---------------------------------------------------------------------- #
# read_records (public entry point)
# ---------------------------------------------------------------------- #


def test_read_records_infers_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    assert read_records(p) == [{"a": 1}]


def test_read_records_infers_json(tmp_path: Path) -> None:
    p = tmp_path / "d.json"
    p.write_text('[{"a": 1}]', encoding="utf-8")
    assert read_records(p) == [{"a": 1}]


def test_read_records_explicit_type_overrides_extension(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
    assert read_records(p, "jsonl") == [{"a": 1}, {"b": 2}]


def test_read_records_explicit_type_is_case_insensitive(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    assert read_records(p, "JSONL") == [{"a": 1}]


def test_read_records_unsupported_explicit_type_raises(tmp_path: Path) -> None:
    p = tmp_path / "data.txt"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported dataset type"):
        read_records(p, "csv")


def test_read_records_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Dataset file not found"):
        read_records(tmp_path / "missing.jsonl")


def test_read_records_accepts_str_path(tmp_path: Path) -> None:
    p = tmp_path / "d.jsonl"
    p.write_text('{"a": 1}\n', encoding="utf-8")
    assert read_records(str(p)) == [{"a": 1}]
