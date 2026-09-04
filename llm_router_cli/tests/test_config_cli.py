"""
Tests for the ``llm-router config`` CLI command (discover / merge + --verbose).

``discover`` is exercised against an unreachable loopback port so the probe
failure path (and its verbose trace) is deterministic and offline.
"""

from __future__ import annotations

import json

from llm_router_cli.cli.commands.config import ConfigCommand


# ---- help / dispatch ------------------------------------------------------


def test_discover_help_has_verbose(capsys):
    assert ConfigCommand.run(["discover", "--help"]) == 0
    assert "--verbose" in capsys.readouterr().out


def test_merge_help_has_verbose(capsys):
    assert ConfigCommand.run(["merge", "--help"]) == 0
    assert "--verbose" in capsys.readouterr().out


def test_bare_config_shows_help(capsys):
    assert ConfigCommand.run([]) == 0
    out = capsys.readouterr().out
    assert "discover" in out and "merge" in out


# ---- verbose --------------------------------------------------------------


def test_discover_verbose_logs_probes(capsys, caplog):
    """A dead loopback port must produce a visible probe trace."""
    rc = ConfigCommand.run(["discover", "127.0.0.1:9", "--verbose"])
    assert rc == 0  # empty config + warning on stderr is the contract
    err = capsys.readouterr().err
    assert "no local providers found" in err

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    # the discovery trace: which host was probed and how the probes failed
    assert "Discovering on 1 host(s): 127.0.0.1:9" in log_text
    assert "127.0.0.1:9" in log_text and "Probe" in log_text
    assert "Discover complete: 0 model group(s)" in log_text


def test_merge_verbose_logs_per_file_and_summary(tmp_path, capsys, caplog):
    def _cfg(name: str, model: str) -> None:
        path = tmp_path / name
        path.write_text(
            json.dumps(
                {
                    f"{model}_models": {
                        model: {
                            "providers": [
                                {
                                    "id": f"{model}_p1",
                                    "api_host": "http://localhost:11434",
                                    "api_type": "ollama",
                                }
                            ],
                            "providers_sleep": [],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    _cfg("a.json", "alpha")
    _cfg("b.json", "beta")

    rc = ConfigCommand.run(
        ["merge", str(tmp_path / "a.json"), str(tmp_path / "b.json"), "--verbose"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    merged = json.loads(out)
    assert "alpha_models" in merged and "beta_models" in merged

    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "Merge: loaded" in log_text
    assert "Merge complete: 2 group(s) from 2 file(s), 0 skipped" in log_text


def test_merge_verbose_reports_skipped_file(tmp_path, capsys, caplog):
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"x_models": {"m": {"providers": []}}}), encoding="utf-8"
    )
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")

    rc = ConfigCommand.run(["merge", str(good), str(bad), "--verbose"])
    assert rc == 0
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    assert "skipping" in log_text and str(bad) in log_text
    assert "Merge complete: 1 group(s) from 2 file(s), 1 skipped" in log_text
