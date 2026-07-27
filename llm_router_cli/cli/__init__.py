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
"""

from __future__ import annotations

import sys
import argparse

from importlib.metadata import version as _pkg_version

# Mark this as a CLI run before any import from ``llm_router_api`` that could
# trigger the startup configuration validation (in ``constants.py``).
import llm_router_api.base.const_global as _cg

_cg.IS_CLI_COMMAND = True


def _version() -> str:
    """Return the installed package version (e.g. ``0.6.0``)."""
    return _pkg_version("llm-router")


def main(argv: list[str] | None = None) -> int:
    """
    Top-level CLI entry point.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit code.
    """
    argv = argv if argv is not None else sys.argv[1:]

    # Version-only parser — all subcommands are delegated to auth / config / anonymizer.
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

    # Register the ``auth`` subparser with its own sub-commands (key, policy).
    from .commands.auth import AuthCommand  # noqa: E402

    auth_parser = subparsers.add_parser(
        "auth",
        help="Manage API keys and authentication",
    )
    auth_sub = auth_parser.add_subparsers(dest="auth_command")
    AuthCommand.register_parser(auth_sub, nest_auth=False)  # type: ignore[arg-type]

    # Register the ``anonymizer`` subparser.
    from .commands.anonymizer import (  # noqa: E402
        AnonymizerCommand,
    )

    anon_parser = subparsers.add_parser(
        "anonymizer",
        help="Anonymise text using a selectable algorithm",
    )
    anon_sub = anon_parser.add_subparsers(dest="anonymizer_command")
    AnonymizerCommand.register_parser(anon_sub)  # type: ignore[arg-type]

    # Register the ``config`` subparser
    # (auto-discover local providers and merge configs).
    from .commands.config import ConfigCommand  # noqa: E402

    config_parser = subparsers.add_parser(
        "config",
        help="Auto-discover local providers and generate/merge models-config.json",
    )
    config_sub = config_parser.add_subparsers(dest="config_command")
    ConfigCommand.register_parser(config_sub)  # type: ignore[arg-type]

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "auth":
        from .commands.auth import AuthCommand as _AuthCmd

        return _AuthCmd.run(argv[1:])

    if args.command == "config":
        from .commands.config import ConfigCommand as _ConfigCmd

        return _ConfigCmd.run(argv[1:])

    if args.command == "anonymizer":
        from .commands.anonymizer import AnonymizerCommand as _AnonCmd

        return _AnonCmd.run(argv[1:])

    # Unknown command
    parser.print_help()
    return 1
