"""
Tests for the pure helpers of the ``llm-router config`` command:
host parsing, name sanitising, deep merge, provider dedup, active-models
derivation, config loading, provider entry building and debug-field
stripping.

All helpers are exercised directly (no network, no subprocess), so failures
pin down the exact helper contract.
"""

from __future__ import annotations

import argparse
import json

from pathlib import Path

import pytest

from llm_router_cli.cli.commands.config import ConfigCommand as C


# ---------------------------------------------------------------------- #
# _parse_host
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("localhost", ("localhost", 0, "http")),
        ("localhost:8000", ("localhost", 8000, "http")),
        ("127.0.0.1:11434", ("127.0.0.1", 11434, "http")),
        ("http://localhost:8000", ("localhost", 8000, "http")),
        ("https://host:8443", ("host", 8443, "https")),
        ("https://host", ("host", 0, "https")),
        ("[::1]:8000", ("::1", 8000, "http")),
        ("http://[::1]:9000", ("::1", 9000, "http")),
        ("[::1]", ("[::1]", 0, "http")),
        ("weird..host", ("weird..host", 0, "http")),
    ],
)
def test_parse_host_forms(raw: str, expected: tuple) -> None:
    assert C._parse_host(raw) == expected


def test_parse_host_non_numeric_port_keeps_raw() -> None:
    assert C._parse_host("localhost:abc") == ("localhost:abc", 0, "http")


def test_parse_host_multiple_colons_fall_back_to_zero() -> None:
    # >1 colon without a scheme is treated as "no explicit port".
    assert C._parse_host("a:b:c") == ("a:b:c", 0, "http")


# ---------------------------------------------------------------------- #
# _sanitize
# ---------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("plain", "plain"),
        ("a/b/c", "a_b_c"),
        ("a:b", "a_b"),
        ("a b c", "a_b_c"),
        ("mix/ed: name", "mix_ed__name"),
    ],
)
def test_sanitize_replaces_unsafe_characters(raw: str, expected: str) -> None:
    assert C._sanitize(raw) == expected


# ---------------------------------------------------------------------- #
# _deep_merge
# ---------------------------------------------------------------------- #


def test_deep_merge_scalars_overlay_wins() -> None:
    assert C._deep_merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_deep_merge_adds_new_keys() -> None:
    assert C._deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_deep_merge_recurses_into_dicts() -> None:
    base = {"g": {"m1": {"x": 1}, "m2": {"y": 2}}}
    overlay = {"g": {"m1": {"z": 3}}}
    assert C._deep_merge(base, overlay) == {
        "g": {"m1": {"x": 1, "z": 3}, "m2": {"y": 2}}
    }


def test_deep_merge_non_dict_value_replaces_whole_value() -> None:
    # A list overlay must replace the dict (not merge key-by-key).
    assert C._deep_merge({"g": {"a": 1}}, {"g": ["x"]}) == {"g": ["x"]}


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"g": {"a": 1}}
    overlay = {"g": {"b": 2}}
    C._deep_merge(base, overlay)
    assert base == {"g": {"a": 1}}
    assert overlay == {"g": {"b": 2}}


# ---------------------------------------------------------------------- #
# _dedup_providers
# ---------------------------------------------------------------------- #


def test_dedup_providers_keeps_first_per_api_host() -> None:
    group = {
        "m": {
            "providers": [
                {"api_host": "http://a:1", "id": "p1"},
                {"api_host": "http://a:1", "id": "p2-dup"},
                {"api_host": "http://b:2", "id": "p3"},
            ]
        }
    }
    C._dedup_providers(group)
    assert [p["id"] for p in group["m"]["providers"]] == ["p1", "p3"]


def test_dedup_providers_ignores_non_dict_model_entries() -> None:
    group = {"m": "not-a-dict", "n": {"providers": "not-a-list"}}
    C._dedup_providers(group)  # must not raise
    assert group == {"m": "not-a-dict", "n": {"providers": "not-a-list"}}


def test_dedup_providers_missing_providers_key_is_noop() -> None:
    group = {"m": {"providers_sleep": []}}
    C._dedup_providers(group)
    assert group == {"m": {"providers_sleep": []}}


# ---------------------------------------------------------------------- #
# _merge_active_models
# ---------------------------------------------------------------------- #


def test_merge_active_models_extends_existing_group() -> None:
    active: dict = {"g": ["a"]}
    C._merge_active_models({"g": ["b"], "h": ["c"]}, active)
    assert active == {"g": ["a", "b"], "h": ["c"]}


def test_merge_active_models_ignores_non_dict_value() -> None:
    active: dict = {}
    C._merge_active_models(["a", "b"], active)  # type: ignore[arg-type]
    assert active == {}


def test_merge_active_models_ignores_non_list_models() -> None:
    active: dict = {}
    C._merge_active_models({"g": "single"}, active)
    assert active == {}


# ---------------------------------------------------------------------- #
# _active_models_from
# ---------------------------------------------------------------------- #


def test_active_models_from_collects_groups_with_providers() -> None:
    config = {
        "ollama_models": {
            "m1": {"providers": [{"id": "p"}], "providers_sleep": []},
            "m2": {"providers": []},
        },
        "active_models": {"ollama_models": ["m1"]},  # must be skipped
        "not-a-group": "scalar",
    }
    assert C._active_models_from(config) == {"ollama_models": ["m1", "m2"]}


def test_active_models_from_ignores_group_without_providers_key() -> None:
    config = {"g": {"m": {"other": 1}}}
    assert C._active_models_from(config) == {}


# ---------------------------------------------------------------------- #
# _load_config
# ---------------------------------------------------------------------- #


def test_load_config_returns_dict(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert C._load_config(str(path)) == {"a": 1}


def test_load_config_invalid_json_returns_empty(tmp_path: Path, capsys) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert C._load_config(str(path)) == {}
    assert "Error reading" in capsys.readouterr().err


def test_load_config_non_object_returns_empty(tmp_path: Path, capsys) -> None:
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert C._load_config(str(path)) == {}
    assert "expected a JSON object" in capsys.readouterr().err


def test_load_config_missing_file_returns_empty(tmp_path: Path, capsys) -> None:
    assert C._load_config(str(tmp_path / "missing.json")) == {}
    assert "Error reading" in capsys.readouterr().err


# ---------------------------------------------------------------------- #
# _build_provider_entry
# ---------------------------------------------------------------------- #


def test_build_provider_entry_defaults() -> None:
    entry = C._build_provider_entry(
        api_type="ollama", host="host", port=11434, model_name="model-a"
    )
    assert entry == {
        "id": "ollama_model-a_host:11434",
        "api_host": "http://host:11434",
        "api_token": "",
        "api_type": "ollama",
        "input_size": 0,
        "model_path": "model-a",
        "keep_alive": None,
        "tool_calling": False,
    }


def test_build_provider_entry_sanitizes_model_and_host() -> None:
    entry = C._build_provider_entry(
        api_type="vllm", host="h:1", port=8000, model_name="a/b c"
    )
    assert entry["model_path"] == "a_b_c"
    assert entry["api_host"] == "http://h:1:8000"
    assert "_b_c" in entry["id"]


def test_build_provider_entry_protocol_prefix() -> None:
    entry = C._build_provider_entry(
        api_type="vllm",
        host="h",
        port=443,
        model_name="m",
        protocol="https",
    )
    assert entry["api_host"] == "https://h:443"


def test_build_provider_entry_extra_meta_overrides() -> None:
    entry = C._build_provider_entry(
        api_type="vllm",
        host="h",
        port=8000,
        model_name="m",
        extra_meta={"input_size": 4096, "tool_calling": True},
    )
    assert entry["input_size"] == 4096
    assert entry["tool_calling"] is True


def test_build_provider_entry_context_length_maps_to_input_size() -> None:
    for key in ("max_context_length", "root_max_window_tokens"):
        entry = C._build_provider_entry(
            api_type="vllm",
            host="h",
            port=8000,
            model_name="m",
            extra_meta={key: 12345},
        )
        assert entry["input_size"] == 12345


def test_build_provider_entry_non_int_context_length_ignored() -> None:
    entry = C._build_provider_entry(
        api_type="vllm",
        host="h",
        port=8000,
        model_name="m",
        extra_meta={"max_context_length": "big"},
    )
    assert entry["input_size"] == 0


def test_build_provider_entry_none_extra_meta_is_fine() -> None:
    entry = C._build_provider_entry(
        api_type="ollama", host="h", port=1, model_name="m", extra_meta=None
    )
    assert entry["input_size"] == 0
    assert entry["tool_calling"] is False


# ---------------------------------------------------------------------- #
# _strip_debug_fields
# ---------------------------------------------------------------------- #


def test_strip_debug_fields_removes_recursively() -> None:
    obj = {
        "group": {
            "model": {
                "providers": [{"id": "p", "models_raw": "x"}],
                "providers_sleep": [],
                "models_raw": ["hidden"],
                "response_format": "openai",
            }
        },
        "active_models": {"group": ["model"]},
    }
    C._strip_debug_fields(obj)
    assert "models_raw" not in obj["group"]["model"]
    assert "response_format" not in obj["group"]["model"]
    assert obj["group"]["model"]["providers"] == [{"id": "p"}]
    assert obj["active_models"] == {"group": ["model"]}


def test_strip_debug_fields_ignores_unrelated_keys() -> None:
    obj = {"group": {"model": {"providers": [{"id": "p"}], "other": 1}}}
    C._strip_debug_fields(obj)
    assert obj == {"group": {"model": {"providers": [{"id": "p"}], "other": 1}}}


# ---------------------------------------------------------------------- #
# _accumulate_group / _add_provider_to_model
# ---------------------------------------------------------------------- #


def test_accumulate_group_creates_new_group() -> None:
    config: dict = {}
    group = {"m1": {"providers": [{"api_host": "http://a:1"}]}}
    C._accumulate_group(config, "grp", group)
    assert config == {"grp": group}


def test_accumulate_group_adds_new_model_to_existing_group() -> None:
    config = {"grp": {"m1": {"providers": [{"api_host": "http://a:1"}]}}}
    C._accumulate_group(
        config, "grp", {"m2": {"providers": [{"api_host": "http://b:2"}]}}
    )
    assert set(config["grp"]) == {"m1", "m2"}


def test_add_provider_to_model_appends_distinct_host() -> None:
    existing = {"providers": [{"api_host": "http://a:1"}]}
    new = {"providers": [{"api_host": "http://b:2"}]}
    C._add_provider_to_model(existing, new)
    assert [p["api_host"] for p in existing["providers"]] == [
        "http://a:1",
        "http://b:2",
    ]


def test_add_provider_to_model_skips_duplicate_host() -> None:
    existing = {"providers": [{"api_host": "http://a:1"}]}
    C._add_provider_to_model(existing, {"providers": [{"api_host": "http://a:1"}]})
    assert len(existing["providers"]) == 1


# ---------------------------------------------------------------------- #
# fetch helpers (network mocked via _get_json)
# ---------------------------------------------------------------------- #


def _ollama_def() -> dict:
    return next(p for p in C.PROVIDER_DEFINITIONS if p["api_type"] == "ollama")


def _vllm_def() -> dict:
    return next(p for p in C.PROVIDER_DEFINITIONS if p["api_type"] == "vllm")


def test_fetch_ollama_models_parses_names_and_context() -> None:
    payload = {
        "models": [
            {
                "name": "llama3:8b",
                "details": {"context_length": 8192},
                "capabilities": [],
            },
            {"name": "no-detail"},
        ]
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_get_json", staticmethod(lambda url, timeout=2.0: payload))
        models = C._fetch_ollama_models("h", 11434)
    assert models == [
        {"id": "llama3:8b", "context_length": 8192, "tool_calling": False},
        {"id": "no-detail", "context_length": None, "tool_calling": False},
    ]


def test_fetch_ollama_models_detects_tool_calling_capability() -> None:
    payload = {
        "models": [
            {
                "name": "m",
                "details": {"capabilities": ["tools"]},
            }
        ]
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_get_json", staticmethod(lambda url, timeout=2.0: payload))
        models = C._fetch_ollama_models("h", 11434)
    assert models[0]["tool_calling"] is True


def test_fetch_ollama_models_skips_entries_without_name() -> None:
    payload = {"models": [{"details": {}}, {"name": "ok"}]}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_get_json", staticmethod(lambda url, timeout=2.0: payload))
        models = C._fetch_ollama_models("h", 11434)
    assert models == [{"id": "ok", "context_length": None, "tool_calling": False}]


def test_fetch_ollama_models_empty_when_json_unavailable() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_get_json", staticmethod(lambda url, timeout=2.0: None))
        assert C._fetch_ollama_models("h", 11434) == []


def test_fetch_openai_style_models_returns_data_list() -> None:
    payload = {"data": [{"id": "m1"}, {"id": "m2"}]}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_get_json", staticmethod(lambda url, timeout=2.0: payload))
        assert C._fetch_openai_style_models("h", 8000) == [
            {"id": "m1"},
            {"id": "m2"},
        ]


def test_fetch_openai_style_models_empty_when_not_a_list() -> None:
    for bad in (None, {"data": "nope"}, {"no_data": 1}):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                C, "_get_json", staticmethod(lambda url, timeout=2.0, b=bad: b)
            )
            assert C._fetch_openai_style_models("h", 8000) == []


def test_build_config_for_provider_groups_models_and_sets_format() -> None:
    raw = [{"id": "m1", "context_length": 4096, "tool_calling": True}]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            C,
            "_fetch_openai_style_models",
            classmethod(lambda cls, host, port, protocol="http": raw),
        )
        group_name, group = C._build_config_for_provider(_vllm_def(), "host", 8000)
    assert group_name == "vllm_models"
    model = group["m1"]
    assert model["response_format"] == "openai"
    assert model["models_raw"] == raw
    provider = model["providers"][0]
    assert provider["api_host"] == "http://host:8000"
    assert provider["input_size"] == 4096
    assert provider["tool_calling"] is True
    assert model["providers_sleep"] == []


def test_build_config_for_provider_ollama_has_no_response_format() -> None:
    raw = [{"id": "m1"}]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            C,
            "_fetch_ollama_models",
            classmethod(lambda cls, host, port, protocol="http": raw),
        )
        _name, group = C._build_config_for_provider(_ollama_def(), "h", 11434)
    assert "response_format" not in group["m1"]


def test_build_config_for_provider_skips_nameless_models() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            C,
            "_fetch_openai_style_models",
            classmethod(lambda cls, host, port, protocol="http": [{"no_id": 1}]),
        )
        _name, group = C._build_config_for_provider(_vllm_def(), "h", 8000)
    assert group == {}


# ---------------------------------------------------------------------- #
# scanning (health check + provider build mocked)
# ---------------------------------------------------------------------- #


def test_scan_provider_skips_unhealthy_port() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_health_check", staticmethod(lambda *a, **k: False))
        mp.setattr(
            C,
            "_build_config_for_provider",
            classmethod(lambda cls, *a, **k: ("g", {"m": {}})),
        )
        assert C._scan_provider("h", 0, "http", _vllm_def()) == []


def test_scan_provider_returns_group_for_healthy_port() -> None:
    group = {"m1": {"providers": [{"api_host": "http://h:8000"}]}}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_health_check", staticmethod(lambda *a, **k: True))
        mp.setattr(
            C,
            "_build_config_for_provider",
            classmethod(lambda cls, prov, host, port, protocol="http": ("g", group)),
        )
        result = C._scan_provider("h", 8000, "http", _vllm_def())
    assert result == [group]


def test_scan_provider_skips_empty_group() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_health_check", staticmethod(lambda *a, **k: True))
        mp.setattr(
            C,
            "_build_config_for_provider",
            classmethod(lambda cls, *a, **k: ("g", {})),
        )
        assert C._scan_provider("h", 8000, "http", _vllm_def()) == []


def test_scan_provider_collect_all_accumulates_multiple_ports() -> None:
    group_a = {"ma": {}}
    group_b = {"mb": {}}
    calls = {"n": 0}

    def build(cls, prov, host, port, protocol="http"):
        calls["n"] += 1
        return "g", group_a if calls["n"] == 1 else group_b

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_health_check", staticmethod(lambda *a, **k: True))
        mp.setattr(C, "_build_config_for_provider", classmethod(build))
        result = C._scan_provider("h", 0, "http", _vllm_def(), collect_all=True)
    assert result == [group_a, group_b]
    assert calls["n"] == 2  # both healthy ports were scanned


def test_scan_provider_stops_at_first_healthy_port_without_collect_all() -> None:
    calls = {"n": 0}

    def build(cls, prov, host, port, protocol="http"):
        calls["n"] += 1
        return "g", {"m": {"i": calls["n"]}}

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_health_check", staticmethod(lambda *a, **k: True))
        mp.setattr(C, "_build_config_for_provider", classmethod(build))
        result = C._scan_provider("h", 0, "http", _vllm_def())
    assert len(result) == 1
    assert calls["n"] == 1


# ---------------------------------------------------------------------- #
# _generate_config (orchestration, scanning mocked)
# ---------------------------------------------------------------------- #


def test_generate_config_merges_groups_per_provider_definition() -> None:
    def scan(cls, host, port, protocol, prov, collect_all=False):
        return [
            {
                "model-x": {
                    "providers": [
                        {
                            "api_host": f"{protocol}://{host}:1",
                            "id": prov["api_type"],
                        }
                    ],
                    "providers_sleep": [],
                    "models_raw": ["secret"],
                }
            }
        ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_scan_provider", classmethod(scan))
        config = C._generate_config([("h", 0, "http")])

    group_names = {p["group_name"] for p in C.PROVIDER_DEFINITIONS}
    assert set(config) == group_names
    for name in group_names:
        assert "models_raw" not in config[name]["model-x"]
        assert config[name]["model-x"]["providers"][0]["id"] in {
            p["api_type"] for p in C.PROVIDER_DEFINITIONS
        }


def test_generate_config_empty_when_nothing_discovered() -> None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_scan_provider", classmethod(lambda cls, *a, **k: []))
        assert C._generate_config([("h", 0, "http")]) == {}


# ---------------------------------------------------------------------- #
# _write_output
# ---------------------------------------------------------------------- #


def test_write_output_to_stdout(capsys) -> None:
    assert C._write_output({"a": 1}, None, "Config") == 0
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_write_output_dash_means_stdout(capsys) -> None:
    assert C._write_output({"a": 1}, "-", "Config") == 0
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_write_output_to_file(tmp_path: Path, capsys) -> None:
    out = tmp_path / "cfg.json"
    assert C._write_output({"a": 1}, str(out), "Config") == 0
    assert json.loads(out.read_text(encoding="utf-8")) == {"a": 1}
    assert "written to" in capsys.readouterr().out


def test_write_output_unwritable_path_returns_1(tmp_path: Path, capsys) -> None:
    # A directory is not a writable file target -> OSError branch.
    assert C._write_output({"a": 1}, str(tmp_path), "Config") == 1
    assert "Error writing" in capsys.readouterr().err


# ---------------------------------------------------------------------- #
# _do_discover / _do_merge end-to-end (all I/O mocked or tmp_path)
# ---------------------------------------------------------------------- #


def _namespace(**overrides) -> argparse.Namespace:
    base = dict(
        hosts=["h"],
        all_ports=False,
        no_active=False,
        output_config_file=None,
        configs=None,
        verbose=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_do_discover_writes_active_models_by_default(tmp_path: Path) -> None:
    out = tmp_path / "cfg.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            C,
            "_scan_provider",
            classmethod(
                lambda cls, *a, **k: [
                    {
                        "m1": {
                            "providers": [{"api_host": "http://h:8000"}],
                            "providers_sleep": [],
                        }
                    }
                ]
            ),
        )
        rc = C._do_discover(_namespace(hosts=["h"], output_config_file=str(out)))
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["active_models"]
    for group in data["active_models"].values():
        assert "m1" in group


def test_do_discover_no_active_omits_active_models(tmp_path: Path) -> None:
    out = tmp_path / "cfg.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            C,
            "_scan_provider",
            classmethod(
                lambda cls, *a, **k: [
                    {"m1": {"providers": [{"api_host": "http://h:8000"}]}}
                ]
            ),
        )
        rc = C._do_discover(
            _namespace(hosts=["h"], no_active=True, output_config_file=str(out))
        )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "active_models" not in data


def test_do_discover_warns_when_nothing_found(capsys, tmp_path: Path) -> None:
    out = tmp_path / "cfg.json"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(C, "_scan_provider", classmethod(lambda cls, *a, **k: []))
        rc = C._do_discover(_namespace(hosts=["h"], output_config_file=str(out)))
    assert rc == 0
    err = capsys.readouterr().err
    assert "no local providers found" in err


def test_do_merge_combines_groups_and_unions_active_models(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(
        json.dumps(
            {
                "vllm_models": {
                    "m1": {"providers": [{"api_host": "http://a:8000", "id": "pa"}]}
                },
                "active_models": {"vllm_models": ["m1"]},
            }
        ),
        encoding="utf-8",
    )
    b.write_text(
        json.dumps(
            {
                "vllm_models": {
                    "m2": {"providers": [{"api_host": "http://b:8000", "id": "pb"}]}
                },
                "active_models": {"vllm_models": ["m2"]},
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "merged.json"
    rc = C._do_merge(
        _namespace(configs=[str(a), str(b)], output_config_file=str(out))
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["vllm_models"]) == {"m1", "m2"}
    assert set(data["active_models"]["vllm_models"]) == {"m1", "m2"}


def test_do_merge_dedups_duplicate_providers(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(
        json.dumps(
            {
                "vllm_models": {
                    "m1": {
                        "providers": [
                            {"api_host": "http://a:8000", "id": "p1"},
                            {"api_host": "http://a:8000", "id": "p1-dup"},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    b.write_text(json.dumps({}), encoding="utf-8")
    out = tmp_path / "merged.json"
    rc = C._do_merge(
        _namespace(configs=[str(a), str(b)], output_config_file=str(out))
    )
    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    providers = data["vllm_models"]["m1"]["providers"]
    assert [p["id"] for p in providers] == ["p1"]


def test_do_merge_skips_unreadable_file_with_warning(tmp_path: Path, capsys) -> None:
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"vllm_models": {"m1": {"providers": []}}}), encoding="utf-8"
    )
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    out = tmp_path / "merged.json"
    rc = C._do_merge(
        _namespace(configs=[str(good), str(bad)], output_config_file=str(out))
    )
    assert rc == 0
    assert "skipped unreadable file" in capsys.readouterr().err
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "m1" in data["vllm_models"]
