"""
Tests for the ``llm-router anonymizer`` subcommand.

The ``fast_masker`` plugin package is replaced with a deterministic fake
(injected into ``sys.modules``) so the suite exercises the CLI's own logic —
rule selection, STDIN/STDOUT handling and file in/out — without depending on
the plugin being installed.
"""

from __future__ import annotations

import io
import sys
import types

import pytest

from llm_router_cli.cli import main
from llm_router_cli.cli.commands.anonymizer import AnonymizerCommand

_MASKER_PATH = "llm_router_plugins.maskers.fast_masker.core.masker"

# (kind -> sentinel) pairs the fake masker knows how to replace.
_SENTINELS = {
    "pesel": "12345678901",
    "email": "jan.kowalski@example.com",
    "ip": "192.168.1.100",
    "url": "https://example.com/x",
    "phone": "512750525",
}

SAMPLE = (
    "pesel 12345678901 email jan.kowalski@example.com ip 192.168.1.100 "
    "url https://example.com/x phone 512750525"
)


def _make_fake_masker_module():
    """Build a fake ``...core.masker`` module with deterministic behaviour."""
    module = types.ModuleType(_MASKER_PATH)

    class _Rule:
        kind = "?"

        def __init__(self) -> None:
            self.name = self.kind.upper()

    def _rule(kind: str):
        return type(f"{kind.capitalize()}Rule", (_Rule,), {"kind": kind})

    class FastMasker:
        instances: list = []

        def __init__(self, rules):
            self.rules = list(rules)
            FastMasker.instances.append(self)

        def mask_text(self, text: str):
            out, mapping = text, {}
            for index, rule in enumerate(self.rules, start=1):
                sentinel = _SENTINELS.get(rule.kind)
                if sentinel and sentinel in out:
                    token = f"{{{rule.kind.upper()}_{index}}}"
                    out = out.replace(sentinel, token)
                    mapping[token] = sentinel
            return out, mapping

    module.PeselRule = _rule("pesel")
    module.EmailRule = _rule("email")
    module.IpRule = _rule("ip")
    module.UrlRule = _rule("url")
    module.PhoneRule = _rule("phone")
    module.FastMasker = FastMasker
    return module


@pytest.fixture
def fake_masker(monkeypatch):
    """Install the deterministic fake ``fast_masker`` plugin module."""
    module = _make_fake_masker_module()
    # Shadow every level of the package path so the lazy import inside
    # ``AnonymizerCommand._mask`` resolves to the fake in any environment.
    parts = _MASKER_PATH.split(".")
    for level in range(1, len(parts) + 1):
        name = ".".join(parts[:level])
        target = module if name == _MASKER_PATH else types.ModuleType(name)
        monkeypatch.setitem(sys.modules, name, target)
    module.FastMasker.instances = []
    return module


# ---- help / dispatch ------------------------------------------------------


def test_bare_anonymizer_shows_help(capsys):
    assert AnonymizerCommand.run([]) == 0
    out = capsys.readouterr().out
    assert "run" in out
    assert "anonymizer" in out.lower()


def test_run_help_lists_all_flags(capsys):
    assert AnonymizerCommand.run(["run", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in (
        "--algorithm",
        "-o",
        "--disable-phone",
        "--disable-url",
        "--disable-ip",
        "--disable-pesel",
        "--disable-email",
    ):
        assert flag in out


def test_algorithm_is_required(capsys):
    # argparse error -> normalised exit code 2 (no traceback).
    assert AnonymizerCommand.run(["run"]) == 2
    assert "required: --algorithm" in capsys.readouterr().err


def test_unknown_algorithm_rejected(capsys):
    assert AnonymizerCommand.run(["run", "--algorithm", "nope"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_pii_algorithm_reported_not_implemented(capsys):
    assert AnonymizerCommand.run(["run", "--algorithm", "pii", "in.txt"]) == 1
    err = capsys.readouterr().err
    assert "not yet implemented" in err
    assert "fast_masker" in err


# ---- fast_masker: rule selection and I/O ----------------------------------


def test_default_rule_set_is_complete_and_masks_stdin_to_stdout(
    fake_masker, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "stdin", io.StringIO(SAMPLE))
    assert AnonymizerCommand.run(["run", "--algorithm", "fast_masker"]) == 0
    out = capsys.readouterr().out
    # No raw PII may survive in the output.
    for sentinel in _SENTINELS.values():
        assert sentinel not in out
    # Every rule kind produced a placeholder.
    for kind in _SENTINELS:
        assert kind.upper() in out
    # Default rule set: all five rules, in the documented order.
    masker = fake_masker.FastMasker.instances[-1]
    assert [r.kind for r in masker.rules] == ["pesel", "email", "ip", "url", "phone"]


def test_disable_flags_remove_only_the_selected_rules(
    fake_masker, monkeypatch, capsys
):
    monkeypatch.setattr(sys, "stdin", io.StringIO(SAMPLE))
    rc = AnonymizerCommand.run(
        [
            "run",
            "--algorithm",
            "fast_masker",
            "--disable-pesel",
            "--disable-ip",
            "--disable-phone",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    masker = fake_masker.FastMasker.instances[-1]
    assert [r.kind for r in masker.rules] == ["email", "url"]
    # Disabled kinds stay verbatim, enabled ones are masked.
    assert _SENTINELS["pesel"] in out
    assert _SENTINELS["ip"] in out
    assert _SENTINELS["phone"] in out
    assert _SENTINELS["email"] not in out
    assert _SENTINELS["url"] not in out


def test_file_input_file_output(fake_masker, tmp_path, capsys):
    src = tmp_path / "in.txt"
    src.write_text(SAMPLE, encoding="utf-8")
    dst = tmp_path / "out.txt"
    assert (
        AnonymizerCommand.run(
            ["run", "--algorithm", "fast_masker", str(src), "-o", str(dst)]
        )
        == 0
    )
    text = dst.read_text(encoding="utf-8")
    for sentinel in _SENTINELS.values():
        assert sentinel not in text
    for kind in _SENTINELS:
        assert kind.upper() in text
    # With an explicit output file nothing may leak to stdout.
    assert capsys.readouterr().out == ""


def test_pre_parsed_file_handles(fake_masker, capsys):
    """Pre-parsed file objects (library use) must be read/written directly."""
    buf_in = io.StringIO(SAMPLE)
    buf_out = io.StringIO()
    args = AnonymizerCommand.build_parser().parse_args(
        ["run", "--algorithm", "fast_masker"]
    )
    args.input = buf_in
    args.output = buf_out
    assert AnonymizerCommand._mask(args) == 0
    text = buf_out.getvalue()
    assert _SENTINELS["email"] not in text
    assert "EMAIL" in text
    assert capsys.readouterr().out == ""


def test_main_dispatches_anonymizer(fake_masker, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("email jan.kowalski@example.com"))
    assert main(["anonymizer", "run", "--algorithm", "fast_masker"]) == 0
    out = capsys.readouterr().out
    assert "jan.kowalski@example.com" not in out
    assert "EMAIL" in out
