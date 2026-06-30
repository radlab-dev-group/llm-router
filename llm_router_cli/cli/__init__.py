"""
llm-router CLI — top-level dispatcher.

Usage::

    llm-router auth key generate  --policy developer
    llm-router auth key list
    llm-router auth key delete <key-id>
    llm-router auth key rotate <key-id>
    llm-router auth policy list
    llm-router auth policy create <name> <json-policy>
    llm-router anonymizer run --algorithm fast_masker [input_file]
"""

from __future__ import annotations

# Mark this as a CLI run before any import from ``llm_router_api`` that could
# trigger the startup configuration validation (in ``constants.py``).
import llm_router_api.base.const_global as _cg  # noqa: E402

_cg.IS_CLI_COMMAND = True

import sys
import argparse


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

    # Version-only parser — all subcommands are delegated to auth / anonymizer.
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

    # Register the ``anonymizer`` subparser with its own ``run`` subcommand.
    anon_parser = subparsers.add_parser(
        "anonymizer",
        help="Anonymise text using a selectable algorithm",
    )
    anon_sub = anon_parser.add_subparsers(dest="anonymizer_command")

    _run_cmd = anon_sub.add_parser(
        "run",
        help="Run text anonymisation",
    )
    _run_cmd.add_argument(
        "--algorithm",
        required=True,
        choices=["fast_masker", "pii"],
        help="Anonymisation algorithm to use (pii is not yet implemented)",
    )
    _run_cmd.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Input file path (defaults to STDIN).",
    )
    _run_cmd.add_argument(
        "-o",
        "--output",
        default="-",
        help="Output file path (defaults to STDOUT).",
    )
    for flag, desc in [
        ("phone", "phone-number anonymisation"),
        ("url", "URL anonymisation"),
        ("ip", "IP-address anonymisation"),
        ("pesel", "PESEL anonymisation"),
        ("email", "e-mail anonymisation"),
    ]:
        _run_cmd.add_argument(
            f"--disable-{flag}",
            action="store_true",
            help=f"Do not apply {desc}.",
        )

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "auth":
        from .commands.auth import main as _auth_main

        return _auth_main(argv[1:])  # strip "auth" off

    if args.command == "anonymizer":
        from .commands.anonymizer import main as _anon_main

        return _anon_main(argv[1:])  # strip "anonymizer" off

    # Unknown command
    parser.print_help()
    return 1
