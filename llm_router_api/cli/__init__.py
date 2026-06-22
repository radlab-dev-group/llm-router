"""
llm-router CLI — top-level dispatcher.

Usage::

    llm-router auth key generate  --policy developer
    llm-router auth key list
    llm-router auth key delete <key-id>
    llm-router auth key rotate <key-id>
    llm-router auth policy list
    llm-router auth policy create <name> <json-policy>
"""

from __future__ import annotations

# Mark this as a CLI run before any import from ``llm_router_api`` that could
# trigger the startup configuration validation (in ``constants.py``).
import llm_router_api.base.const_global as _cg  # noqa: E402

_cg.IS_CLI_COMMAND = True

import argparse
import sys


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

    # Version-only parser — all subcommands are delegated to the auth CLI.
    parser = argparse.ArgumentParser(
        prog="llm-router",
        description="LLM Router CLI — manage API keys, policies, and more",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Register the ``auth`` subparser with its own sub-commands (key, policy).
    from .commands.auth import register_auth_subparser  # noqa: E402

    auth_parser = subparsers.add_parser(
        "auth",
        help="Manage API keys and authentication",
    )
    auth_sub = auth_parser.add_subparsers(dest="auth_command")
    register_auth_subparser(auth_sub, nest_auth=False)

    args = parser.parse_args(argv)

    if (
        args.command is None
        or not hasattr(args, "auth_command")
        or args.auth_command is None
    ):
        parser.print_help()
        return 0

    if args.command == "auth":
        from .commands.auth import main as _auth_main

        return _auth_main(argv[1:])  # strip "auth" off

    # Unknown command
    parser.print_help()
    return 1


# -- version ----------------------------------------------------------
__version__ = "0.5.2"  # keep in sync with .version
