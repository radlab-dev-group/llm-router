"""
No-network tests for the ``util`` apps.

The LLM is never actually called: :meth:`LLMRouterClient.translate` and
:meth:`LLMRouterClient.extended_conversation_with_model` (plus the
:meth:`LLMRouterClient.version` probe) are monkeypatched with deterministic
fake responses, so the whole pipeline (loading, threading, buffering, flushing
and on-disk output) is exercised offline.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pytest

from llm_router_lib.client import LLMRouterClient

from llm_router_cli.util.retry import with_retries
from llm_router_cli.util.translate import TranslateApp
from llm_router_cli.util.genai_classifier import GenAIClassifierApp
from llm_router_cli.util.genai_data_augmentation import GenAIDataAugmentationApp


# --------------------------------------------------------------------- #
# Fake LLM responses / patches
# --------------------------------------------------------------------- #
class _FakeTranslateItem:
    def __init__(self, original: str, translated: str):
        self.original = original
        self.translated = translated


class _FakeTranslateResponse:
    def __init__(self, items):
        self.response = items


def _fake_translate(self, model=None, texts=None, **kwargs):  # noqa: ANN001
    return _FakeTranslateResponse(
        [_FakeTranslateItem(t, f"TR:{t}") for t in (texts or [])]
    )


class _FakeConvResponse:
    def __init__(self, text: str):
        self.response = text


class _FakeVersionResponse:
    version = "9.9.9-test"


@pytest.fixture
def fake_translate(monkeypatch):
    monkeypatch.setattr(LLMRouterClient, "translate", _fake_translate)
    return _fake_translate


def _install_fake_extended(monkeypatch, payload_json: str):
    """Install a fake ``extended_conversation_with_model`` returning *payload_json*."""

    def _fake_extended(
        self,
        user_last_statement=None,
        system_prompt=None,
        model=None,
        temperature=None,
        **kwargs,
    ):  # noqa: ANN001
        return _FakeConvResponse(payload_json)

    monkeypatch.setattr(
        LLMRouterClient, "extended_conversation_with_model", _fake_extended
    )
    return _fake_extended


@pytest.fixture
def fake_conversation(monkeypatch):
    return _install_fake_extended(
        monkeypatch, '{"exists": true, "class": "feature1", "confidence": 0.9}'
    )


@pytest.fixture
def fake_augmentation(monkeypatch):
    return _install_fake_extended(
        monkeypatch, '{"augmented_examples": ["ex-1", "ex-2"], "note": "ok"}'
    )


@pytest.fixture
def fake_version(monkeypatch):
    monkeypatch.setattr(
        LLMRouterClient, "version", lambda self, **kw: _FakeVersionResponse()
    )
    return lambda self, **kw: _FakeVersionResponse()


def _write_jsonl(path: Path, records) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path):
    records = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# --------------------------------------------------------------------- #
# translate
# --------------------------------------------------------------------- #
def _translate_args(dataset_paths, accept_field=None, output=None):
    return argparse.Namespace(
        llm_router_host="http://localhost:8080",
        llm_router_token=None,
        llm_router_timeout=10,
        model="test-model",
        dataset_path=list(dataset_paths),
        dataset_type=None,
        accept_field=list(accept_field or []),
        num_workers=1,
        batch_size=8,
        output=output,
    )


def test_translate_writes_translated_jsonl_next_to_input(tmp_path, fake_translate):
    data_file = tmp_path / "data.jsonl"
    _write_jsonl(data_file, [{"text": "hello", "title": "world"}])
    before = data_file.read_text(encoding="utf-8")

    app = TranslateApp(_translate_args([data_file], accept_field=["text", "title"]))
    app.run()
    app.close()

    out_file = tmp_path / "data.translated.jsonl"
    assert out_file.is_file(), "expected data.translated.jsonl next to input"
    records = _read_jsonl(out_file)
    assert records == [{"text": "TR:hello", "title": "TR:world"}]

    # The input file must be left untouched.
    assert data_file.read_text(encoding="utf-8") == before


def test_translate_single_output_file(tmp_path, fake_translate):
    f1 = tmp_path / "a.jsonl"
    f2 = tmp_path / "b.jsonl"
    _write_jsonl(f1, [{"text": "one"}])
    _write_jsonl(f2, [{"text": "two"}, {"text": "three"}])

    out_file = tmp_path / "merged" / "all.jsonl"
    app = TranslateApp(
        _translate_args([f1, f2], accept_field=["text"], output=str(out_file))
    )
    app.run()
    app.close()

    records = _read_jsonl(out_file)
    assert records == [{"text": "TR:one"}, {"text": "TR:two"}, {"text": "TR:three"}]
    # No per-input files should be created when -o is used.
    assert not (tmp_path / "a.translated.jsonl").exists()
    assert not (tmp_path / "b.translated.jsonl").exists()


def test_translate_accept_field_filters(tmp_path, fake_translate):
    data_file = tmp_path / "data.jsonl"
    _write_jsonl(data_file, [{"text": "hello", "keep": "x", "drop": "y"}])

    app = TranslateApp(_translate_args([data_file], accept_field=["text"]))
    app.run()
    app.close()

    records = _read_jsonl(tmp_path / "data.translated.jsonl")
    assert records == [{"text": "TR:hello"}]
    # Only the accepted field is present in the output record.
    assert set(records[0].keys()) == {"text"}


def test_translate_empty_file_no_error(tmp_path, fake_translate):
    data_file = tmp_path / "empty.jsonl"
    data_file.write_text("", encoding="utf-8")

    app = TranslateApp(_translate_args([data_file], accept_field=["text"]))
    app.run()  # must not raise
    app.close()

    out_file = tmp_path / "empty.translated.jsonl"
    assert out_file.is_file()
    assert not _read_jsonl(out_file)


# --------------------------------------------------------------------- #
# genai-classifier
# --------------------------------------------------------------------- #
def test_classifier_writes_jsonl_no_xlsx(tmp_path, fake_conversation, fake_version):
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    _write_jsonl(
        dataset_dir / "data.jsonl",
        [{"Tekst": "t1"}, {"Tekst": "t2"}, {"Tekst": "t3"}],
    )

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "feature1.prompt").write_text(
        "Classify the text. Respond with JSON.", encoding="utf-8"
    )

    output_dir = tmp_path / "out"
    output_dir.mkdir()

    app = GenAIClassifierApp(
        dataset_dir=dataset_dir,
        prompts_dir=prompts_dir,
        llm_router_url="http://localhost:8080",
        model_name="gpt-oss:120b",
        temperature=0.0,
        batch_save_size=5,
        dry_run=False,
        output_dir=output_dir,
        verbose=False,
        num_workers=2,
        n_sample=None,  # process all
        dataset_paths=[],
        text_column_name="Tekst",
    )
    app.run()

    main_out = output_dir / "data.jsonl"
    clean_out = output_dir / "data_clean_labels.jsonl"
    assert main_out.is_file()
    assert clean_out.is_file()

    records = _read_jsonl(main_out)
    assert len(records) == 3
    for rec in records:
        assert rec["field"] == "Tekst"
        assert rec["text"] in {"t1", "t2", "t3"}
        feats = {f["name"]: f["response"] for f in rec["features"]}
        assert feats["feature1"]["exists"] is True

    clean = _read_jsonl(clean_out)
    assert len(clean) == 3
    assert all(rec["labels"] == ["feature1"] for rec in clean)

    # No XLSX anywhere in the output dir.
    assert not list(output_dir.glob("*.xlsx")), "XLSX output must not be produced"


# --------------------------------------------------------------------- #
# genai-data-augmentation
# --------------------------------------------------------------------- #
def test_augmentation_writes_jsonl_and_train_no_xlsx(tmp_path, fake_augmentation):
    dataset_path = tmp_path / "dataset.jsonl"
    _write_jsonl(
        dataset_path,
        [
            {"Tekst": "text-0", "label": "cat"},
            {"Tekst": "text-1", "label": "cat"},
            {"Tekst": "text-2", "label": "dog"},
        ],
    )

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(
        "Augment {CLASS_LIST_PLACEHOLDER}. Give {SAMPLES_PER_CLASS_PLACEHOLDER} examples.\n"
        "{CLASS_EXAMPLES_PLACEHOLDER}",
        encoding="utf-8",
    )

    app = GenAIDataAugmentationApp(
        dataset_path=dataset_path,
        prompt_path=prompt_file,
        labels=["cat"],
        llm_router_url="http://localhost:8080",
        model_name="gpt-oss:120b",
        temperature=0.7,
        n_samples=5,
        n_examples=3,
        samples_as_examples=5,
        batch_save_size=5,
        dry_run=False,
        output_dir=None,
        verbose=False,
        num_workers=2,
        text_column_name="Tekst",
        label_column_name="label",
        retry_attempts=2,
        retry_wait=0.0,
    )
    app.run()

    aug_out = tmp_path / "dataset_augmented.jsonl"
    train_out = tmp_path / "dataset_augmented-train.jsonl"
    assert aug_out.is_file()
    assert train_out.is_file()

    records = _read_jsonl(aug_out)
    # Only the two "cat" records are processed (dog is filtered out).
    assert {r["original_text"] for r in records} == {"text-0", "text-1"}
    assert all(r["labels"] == ["cat"] for r in records)
    # The parsed augmented payload is merged into the record.
    assert all(r.get("augmented_examples") == ["ex-1", "ex-2"] for r in records)

    train = _read_jsonl(train_out)
    # Each of the 2 records contributes 2 augmented examples.
    assert len(train) == 4
    assert all(t["labels"] == ["cat"] for t in train)

    # No XLSX anywhere in the dataset dir.
    assert not list(tmp_path.glob("*.xlsx")), "XLSX output must not be produced"


# --------------------------------------------------------------------- #
# retry helper
# --------------------------------------------------------------------- #
def test_with_retries_succeeds_on_nth_attempt():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("boom")
        return "ok"

    result = with_retries(flaky, attempts=5, wait=0.0)
    assert result == "ok"
    assert calls["n"] == 3


def test_with_retries_raises_after_exceeding_attempts():
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError, match="nope"):
        with_retries(always_fail, attempts=3, wait=0.0)
    assert calls["n"] == 3


def test_with_retries_single_attempt():
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise ValueError("x")

    with pytest.raises(ValueError):
        with_retries(always_fail, attempts=1, wait=0.0)
    assert calls["n"] == 1


def test_with_retries_propagates_non_retriable_immediately():
    calls = {"n": 0}

    def raise_type_error():
        calls["n"] += 1
        raise TypeError("not retriable")

    with pytest.raises(TypeError):
        with_retries(
            raise_type_error,
            attempts=5,
            wait=0.0,
            retry_on=(ValueError,),
        )
    assert calls["n"] == 1


def test_with_retries_invalid_attempts():
    with pytest.raises(ValueError):
        with_retries(lambda: 1, attempts=0)


# --------------------------------------------------------------------- #
# --verbose / logging
# --------------------------------------------------------------------- #
def test_setup_logging_levels_and_idempotency():
    from llm_router_cli.log_utils import setup_logging

    root = logging.getLogger()
    original = (root.level, list(root.handlers))
    added = []
    try:
        setup_logging(verbose=False)
        assert root.level == logging.INFO
        n_handlers = len(root.handlers)
        assert n_handlers >= 1
        setup_logging(verbose=False)  # idempotent: no handler duplication
        assert len(root.handlers) == n_handlers
        setup_logging(verbose=True)
        assert root.level == logging.DEBUG
        assert len(root.handlers) == n_handlers
        for h in root.handlers[n_handlers - len(added) :]:
            added.append(h)
    finally:
        for h in list(root.handlers):
            if h not in original[1]:
                root.removeHandler(h)
        root.setLevel(original[0])
        root.handlers[:] = original[1]


def test_shorten_collapses_lines_and_truncates():
    from llm_router_cli.log_utils import shorten

    assert shorten("hello") == "hello"
    assert shorten("a" * 300, 20).endswith("…")
    assert len(shorten("a" * 300, 20)) == 20
    assert "\n" not in shorten("line1\nline2", 100)


def test_verbose_shows_per_task_and_llm_detail(
    tmp_path, caplog, fake_conversation, fake_version
):
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    (dataset_dir / "data.jsonl").write_text(
        "\n".join(json.dumps({"Tekst": f"t{i}"}) for i in range(4)) + "\n",
        encoding="utf-8",
    )
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "feature1.prompt").write_text("Classify.", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    app = GenAIClassifierApp(
        dataset_dir=dataset_dir,
        prompts_dir=prompts_dir,
        llm_router_url="http://localhost:8080",
        model_name="m",
        temperature=0.0,
        batch_save_size=5,
        dry_run=False,
        output_dir=output_dir,
        verbose=True,
        num_workers=2,
        n_sample=None,
        dataset_paths=[],
        text_column_name="Tekst",
    )
    with caplog.at_level(logging.DEBUG):
        app.run()

    messages = [r.getMessage() for r in caplog.records]
    # pipeline-level detail (what is happening per task)
    assert any(m.startswith("Task done in") for m in messages), messages
    # LLM-level detail (what is sent / what comes back)
    assert any("Classifying (feature=" in m for m in messages), messages
    assert any("LLM raw response" in m for m in messages), messages
    # secrets must never leak into logs
    assert not any("llm_router_token" in m and "token=" in m for m in messages)


def test_verbose_config_dump_masks_token(
    tmp_path, caplog, fake_conversation, fake_version
):
    dataset_dir = tmp_path / "datasets"
    dataset_dir.mkdir()
    (dataset_dir / "data.jsonl").write_text(
        json.dumps({"Tekst": "t1"}) + "\n", encoding="utf-8"
    )
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "feature1.prompt").write_text("Classify.", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    secret = "super-secret-token-123"
    app = GenAIClassifierApp(
        dataset_dir=dataset_dir,
        prompts_dir=prompts_dir,
        llm_router_url="http://localhost:8080",
        model_name="m",
        llm_router_token=secret,
        temperature=0.0,
        batch_save_size=5,
        dry_run=False,
        output_dir=output_dir,
        verbose=True,
        num_workers=1,
        n_sample=None,
        dataset_paths=[],
        text_column_name="Tekst",
    )
    with caplog.at_level(logging.DEBUG):
        app.run()

    all_text = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in all_text, "the token must never appear in logs"
    assert "'llm_router_token': '***'" in all_text
