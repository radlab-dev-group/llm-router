"""
CLI-level tests for the ``llm-router util`` subcommand group.

Covers ``--help`` dispatch for all three sub-subcommands, the bare ``util``
help, wiring through the top-level ``main`` dispatcher, and a *leak guard*
that proves importing the new ``util`` apps does **not** pull in the heavy
libraries (``datasets`` / ``pandas`` / ``openpyxl`` / ``tenacity``) the port
was explicitly meant to drop.
"""

from __future__ import annotations

import sys

import pytest

from llm_router_cli.cli import main
from llm_router_cli.cli.commands.util import UtilCommand

_HEAVY_MODULES = ("datasets", "pandas", "openpyxl", "tenacity")


def _run(argv):
    """
    Run *argv* through :func:`main`, normalizing both a returned exit code and
    an argparse ``SystemExit`` (raised by ``--help``) to an int.
    """
    try:
        return main(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1


def _cmd(argv):
    """Run *argv* through :meth:`UtilCommand.run`, normalizing ``SystemExit``."""
    try:
        return UtilCommand.run(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1


# ---- help / dispatch ------------------------------------------------------


def test_util_bare_help_rc0(capsys):
    assert UtilCommand.run([]) == 0
    out = capsys.readouterr().out
    for cmd in ("translate", "genai-classifier", "genai-data-augmentation"):
        assert cmd in out


def test_translate_help_rc0_and_flags(capsys):
    assert UtilCommand.run(["translate", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in (
        "--llm-router-host",
        "--llm-router-token",
        "--llm-router-timeout",
        "--model",
        "--dataset-path",
        "--dataset-type",
        "--accept-field",
        "--num-workers",
        "--batch-size",
        "-o",
        "--output",
    ):
        assert flag in out
    # The old generated names must NOT appear.
    assert "--llm-router-host-token" not in out
    assert "--llm-router-host-timeout" not in out


def test_classifier_help_rc0_and_flags(capsys):
    assert UtilCommand.run(["genai-classifier", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in (
        "--dataset-dir",
        "--dataset-path",
        "--prompts-dir",
        "--output-dir",
        "--model-name",
        "--temperature",
        "--num-workers",
        "--n-sample",
        "--batch-save-size",
        "--text-column-name",
        "--dry-run",
        "--verbose",
        "--llm-router-url",
        "--llm-router-token",
        "--llm-router-timeout",
    ):
        assert flag in out
    # XLSX export must be gone.
    assert "--export-xlsx" not in out
    assert "--no-export-xlsx" not in out


def test_augmentation_help_rc0_and_flags(capsys):
    assert UtilCommand.run(["genai-data-augmentation", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in (
        "--dataset-path",
        "--prompt-file",
        "--labels",
        "--n-samples",
        "--n-examples",
        "--samples-as-examples",
        "--num-workers",
        "--batch-save-size",
        "--text-column-name",
        "--label-column-name",
        "--model-name",
        "--temperature",
        "--output-dir",
        "--dry-run",
        "--verbose",
        "--llm-router-url",
    ):
        assert flag in out
    assert "--export-xlsx" not in out
    assert "--no-export-xlsx" not in out


def test_main_util_translate_help():
    assert _run(["util", "translate", "--help"]) == 0


def test_main_util_classifier_help():
    assert _run(["util", "genai-classifier", "--help"]) == 0


def test_main_util_bare_help(capsys):
    assert _run(["util"]) == 0
    out = capsys.readouterr().out
    assert "genai-classifier" in out
    assert "genai-data-augmentation" in out


def test_default_router_url_is_localhost(capsys):
    # The hard-coded LAN IP default from the upstream tool must be replaced.
    assert _run(["util", "genai-classifier", "--help"]) == 0
    out = capsys.readouterr().out
    assert "http://localhost:8080" in out
    assert "192.168.100.65" not in out


# ---- leak guard -----------------------------------------------------------


def test_no_heavy_dependencies_leak():
    """Importing the util apps must not import the dropped heavy libraries."""
    # Ensure a clean slate for the modules under test.
    for name in _HEAVY_MODULES:
        sys.modules.pop(name, None)
    # Also drop any cached util sub-modules so we re-import from scratch.
    for name in list(sys.modules):
        if name.startswith("llm_router_cli.util"):
            sys.modules.pop(name, None)

    import importlib

    import llm_router_cli.util  # noqa: F401

    importlib.reload(llm_router_cli.util)
    import llm_router_cli.util.loaders  # noqa: F401
    import llm_router_cli.util.retry  # noqa: F401
    import llm_router_cli.util.translate  # noqa: F401
    import llm_router_cli.util.genai_classifier  # noqa: F401
    import llm_router_cli.util.genai_data_augmentation  # noqa: F401

    leaked = [m for m in _HEAVY_MODULES if m in sys.modules]
    assert not leaked, f"heavy dependencies leaked into sys.modules: {leaked}"


@pytest.mark.parametrize(
    "subcommand",
    ["translate", "genai-classifier", "genai-data-augmentation"],
)
def test_subcommand_help_via_main_returns_zero(subcommand):
    assert _run(["util", subcommand, "--help"]) == 0
