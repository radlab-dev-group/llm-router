"""
Tests for the CLI base infrastructure: :class:`BaseCommand` mechanics
(exit-code normalisation, verbose flag, standalone ``run`` entry point,
parser building, registration) and the top-level :func:`main` dispatcher
(help, ``--version``, unknown commands).
"""

from __future__ import annotations

import argparse

import pytest

from llm_router_cli.cli import COMMANDS, main
from llm_router_cli.cli.commands.base import BaseCommand, _exit_code


# ---------------------------------------------------------------------- #
# _exit_code
# ---------------------------------------------------------------------- #


def test_exit_code_none_maps_to_zero() -> None:
    assert _exit_code(SystemExit()) == 0


def test_exit_code_int_preserved() -> None:
    assert _exit_code(SystemExit(3)) == 3
    assert _exit_code(SystemExit(0)) == 0


def test_exit_code_string_maps_to_one() -> None:
    assert _exit_code(SystemExit("boom")) == 1


# ---------------------------------------------------------------------- #
# add_verbose
# ---------------------------------------------------------------------- #


def test_add_verbose_flag_defaults_false() -> None:
    parser = argparse.ArgumentParser()
    BaseCommand.add_verbose(parser)
    assert parser.parse_args([]).verbose is False
    assert parser.parse_args(["--verbose"]).verbose is True


# ---------------------------------------------------------------------- #
# BaseCommand contract
# ---------------------------------------------------------------------- #


def test_base_dispatch_and_register_children_raise() -> None:
    with pytest.raises(NotImplementedError):
        BaseCommand.dispatch(argparse.Namespace())
    with pytest.raises(NotImplementedError):
        BaseCommand.register_children(
            argparse.ArgumentParser().add_subparsers(dest="x")
        )


class _DemoCommand(BaseCommand):
    NAME = "demo"
    HELP = "demo help"
    SUBPARSER_DEST = "demo_command"
    last_args: argparse.Namespace | None = None

    @classmethod
    def register_children(cls, subparsers) -> None:
        p = subparsers.add_parser("go", help="go help")
        p.add_argument("value")

    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        cls.last_args = args
        return 7


def test_build_parser_prog_and_description() -> None:
    parser = _DemoCommand.build_parser()
    assert parser.prog == "llm-router demo"
    assert parser.description == "demo help"


def test_register_returns_subparser() -> None:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command")
    parser = _DemoCommand.register(sub)
    assert sub.choices["demo"] is parser
    assert "go" in parser._subparsers._group_actions[0].choices


def test_run_dispatches_standalone() -> None:
    assert _DemoCommand.run(["go", "v1"]) == 7
    assert _DemoCommand.last_args.demo_command == "go"
    assert _DemoCommand.last_args.value == "v1"


def test_run_tolerates_redundant_leading_command_name() -> None:
    assert _DemoCommand.run(["demo", "go", "v2"]) == 7
    assert _DemoCommand.last_args.value == "v2"


def test_run_help_returns_zero(capsys) -> None:
    assert _DemoCommand.run(["go", "--help"]) == 0
    assert "value" in capsys.readouterr().out


def test_run_argparse_error_returns_two(capsys) -> None:
    assert _DemoCommand.run(["go"]) == 2
    assert "required: value" in capsys.readouterr().err


def test_run_no_subcommand_dispatches_default() -> None:
    # Without a sub-command the namespace simply lacks the dest field.
    assert _DemoCommand.run([]) == 7
    assert _DemoCommand.last_args.demo_command is None


# ---------------------------------------------------------------------- #
# COMMANDS registry
# ---------------------------------------------------------------------- #


def test_commands_registry_is_complete_and_ordered() -> None:
    names = [cmd.NAME for cmd in COMMANDS]
    assert names == ["auth", "anonymizer", "config", "completion", "server", "util"]
    assert len(set(names)) == len(names)
    for cmd in COMMANDS:
        assert cmd.HELP
        assert issubclass(cmd, BaseCommand)


# ---------------------------------------------------------------------- #
# main() dispatcher
# ---------------------------------------------------------------------- #


def test_main_no_command_prints_help(capsys) -> None:
    assert main([]) == 0
    out = capsys.readouterr().out
    for name in ("auth", "anonymizer", "config", "util"):
        assert name in out


def test_main_version_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "llm-router" in capsys.readouterr().out


def test_main_unknown_command_exits_two(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_main_bare_subcommand_prints_its_help(capsys) -> None:
    assert main(["config"]) == 0
    out = capsys.readouterr().out
    assert "discover" in out and "merge" in out


def test_cli_package_exposes_version_string() -> None:
    import llm_router_cli

    assert isinstance(llm_router_cli.__version__, str)
    assert llm_router_cli.__version__
