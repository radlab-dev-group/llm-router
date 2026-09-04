"""
llm-router CLI — top-level dispatcher.

Usage::

    llm-router auth key generate  --policy developer
    llm-router auth key list
    llm-router auth key delete <key-id>
    llm-router auth key rotate <key-id>
    llm-router auth policy list
    llm-router auth policy create <name> <json-policy>
    llm-router config discover localhost 192.168.1.50 -o models-config.json
    llm-router config merge base.json override.json -o merged-config.json
    llm-router anonymizer run --algorithm fast_masker [input_file]
    llm-router util translate --llm-router-host URL --model M --dataset-path d.jsonl
    llm-router util genai-classifier --dataset-dir DIR --prompts-dir P --output-dir O
    llm-router util genai-data-augmentation --dataset-path d.jsonl --prompt-file P \
        --labels a,b

The dispatcher builds a single top‑level parser, registers every command once
(see :mod:`llm_router_cli.cli.commands.base`), parses the arguments a single
time and dispatches on the resulting namespace.
"""

# The command modules must be imported *after* ``IS_CLI_COMMAND`` is set below,
# so those imports are intentionally not at the top of the module.
# pylint: disable=wrong-import-position
from __future__ import annotations

import sys
import argparse

from typing import List, Optional, Tuple, Type
from importlib.metadata import version as _pkg_version

# Mark this as a CLI run before any import from ``llm_router_api`` that could
# trigger the startup configuration validation (in ``constants.py``).
import llm_router_api.base.const_global as _cg

_cg.IS_CLI_COMMAND = True

from llm_router_cli.cli.commands.anonymizer import AnonymizerCommand
from llm_router_cli.cli.commands.auth import AuthCommand
from llm_router_cli.cli.commands.base import BaseCommand
from llm_router_cli.cli.commands.config import ConfigCommand
from llm_router_cli.cli.commands.util import UtilCommand

#: All top‑level commands, in the order they appear in the help text.
COMMANDS: Tuple[Type[BaseCommand], ...] = (
    AuthCommand,
    AnonymizerCommand,
    ConfigCommand,
    UtilCommand,
)


def _version() -> str:
    """Return the installed package version (e.g. ``0.6.0``)."""
    try:
        return _pkg_version("llm-router")
    except Exception:  # PackageNotFoundError — e.g. run from a bare checkout
        return "unknown"


def main(argv: Optional[List[str]] = None) -> int:
    """
    Top-level CLI entry point.

    Parameters
    ----------
    argv : Optional[List[str]]
        Command-line arguments. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit code.
    """
    argv = argv if argv is not None else sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="llm-router",
        description="LLM Router CLI — manage API keys, policies, and more",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version()}",
        help="Show program version and exit",
    )
    subparsers = parser.add_subparsers(dest="command")
    for command in COMMANDS:
        command.register(subparsers)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    by_name = {command.NAME: command for command in COMMANDS}
    command_cls = by_name.get(args.command)
    if command_cls is None:  # pragma: no cover - parser guarantees a known name
        parser.print_help()
        return 1

    return command_cls.dispatch(args)
