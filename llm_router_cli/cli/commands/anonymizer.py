"""
Anonymiser subcommand for ``llm-router auth``.

Provides text anonymisation via pluggable algorithms.  Currently only the
``fast_masker`` algorithm is implemented; the ``pii`` algorithm will be added
in a future release.

Typical usage::

    llm-router auth anonymizer run --algorithm fast_masker <input_file>
    echo "My phone is +48 123 456 789" | llm-router auth anonymizer run --algorithm fast_masker

Output is written to stdout by default; use ``--output`` / ``-o`` to direct it
to a file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    """Build the parser for the *anonymizer run* sub-subcommand."""
    p = argparse.ArgumentParser(
        prog="llm-router auth anonymizer run",
        description="Run text anonymisation with a selected algorithm.",
    )
    p.add_argument(
        "--algorithm",
        required=True,
        choices=["fast_masker", "pii"],
        help="Anonymisation algorithm to use (pii is not yet implemented)",
    )
    p.add_argument(
        "input",
        nargs="?",
        type=argparse.FileType("r", encoding="utf-8"),
        default=sys.stdin,
        help="Input file (defaults to STDIN).",
    )
    p.add_argument(
        "-o",
        "--output",
        type=argparse.FileType("w", encoding="utf-8"),
        default=sys.stdout,
        help="Output file (defaults to STDOUT).",
    )
    p.add_argument(
        "--disable-phone",
        action="store_true",
        help="Do not apply phone-number anonymisation.",
    )
    p.add_argument(
        "--disable-url",
        action="store_true",
        help="Do not apply URL anonymisation.",
    )
    p.add_argument(
        "--disable-ip",
        action="store_true",
        help="Do not apply IP-address anonymisation.",
    )
    p.add_argument(
        "--disable-pesel",
        action="store_true",
        help="Do not apply PESEL anonymisation.",
    )
    p.add_argument(
        "--disable-email",
        action="store_true",
        help="Do not apply e-mail anonymisation.",
    )
    return p


def register_anonymizer_subparser(parser: argparse.ArgumentParser) -> None:
    """Register the ``anonymizer run`` sub-subparser under the auth group.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The parent parser (or subparsers action) to attach to.
    """
    anonymizer_parser = parser.add_parser(
        "anonymizer",
        help="Anonymise text using a selectable algorithm",
    )
    anon_sub = anonymizer_parser.add_subparsers(dest="anonymizer_command")

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


def main(argv: list[str] | None = None) -> int:
    """Handle the ``anonymizer run`` subcommand (standalone entry point).

    Builds a flat parser directly on "llm-router auth anonymizer" -- no nested
    sub-subparser for "run" -- so it can be called standalone or delegated to.

    Parameters
    ----------
    argv : list[str] | None
        Raw command-line arguments (not including ``anonymizer``).

    Returns
    -------
    int
        Exit code (0 = success, 1 = error).
    """
    if argv is None:
        argv = []

    # Strip the "run" subcommand from argv when called from the top-level CLI
    # (argv = ["run", "--algorithm", ...]).  The flat parser below handles
    # everything after "run" directly.
    if argv and argv[0] == "run":
        argv = argv[1:]

    p = argparse.ArgumentParser(
        prog="llm-router auth anonymizer",
        description="Run text anonymisation with a selected algorithm.",
    )
    p.add_argument(
        "--algorithm",
        required=True,
        choices=["fast_masker", "pii"],
        help="Anonymisation algorithm to use (pii is not yet implemented)",
    )
    p.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Input file path (defaults to STDIN).",
    )
    p.add_argument(
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
        p.add_argument(
            f"--disable-{flag}",
            action="store_true",
            help=f"Do not apply {desc}.",
        )

    args = p.parse_args(argv)
    return _mask(args)


def _handle_anonymizer_from_args(args) -> int:  # noqa: C901
    """Handle the anonymizer ``run`` subcommand from pre-parsed argparse args.

    Called by auth.py which has already parsed all arguments through its parser
    chain (including deeply-nested sub-subparser flags like --disable-*).

    Parameters
    ----------
    args : argparse.Namespace
        Fully-parsed arguments including algorithm, input/output paths, and
        disable flags from the registration sub-subparser.

    Returns
    -------
    int
        Exit code (0 = success, 1 = error).
    """
    return _mask(args)


def _mask(args) -> int:  # noqa: C901
    """Core masking logic shared by ``main`` and the auth dispatcher.

    Handles two calling conventions:
      - ``main()`` (standalone): input/output are FileType file objects.
      - auth dispatcher (_handle_anonymizer_from_args): input/output are
        string paths ("-" means stdin/stdout).
    """
    algorithm = args.algorithm

    if algorithm == "pii":
        print(
            "Error: 'pii' algorithm is not yet implemented. "
            "Use '--algorithm fast_masker' instead.",
            file=sys.stderr,
        )
        return 1

    # Import lazily to avoid pulling in the plugin package at module load time.
    from llm_router_plugins.maskers.fast_masker.core.masker import (
        EmailRule,
        FastMasker,
        IpRule,
        PhoneRule,
        PeselRule,
        UrlRule,
    )

    # Build the rule list respecting disable flags.
    rules = []

    if not args.disable_pesel:
        rules.append(PeselRule())

    if not args.disable_email:
        rules.append(EmailRule())

    if not args.disable_ip:
        rules.append(IpRule())

    if not args.disable_url:
        rules.append(UrlRule())

    if not args.disable_phone:
        rules.append(PhoneRule())

    anonymizer = FastMasker(rules)

    # Handle input – file object (from main) vs string path (from auth dispatcher).
    if isinstance(args.input, str):
        _input_text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    else:
        _input_text = args.input.read()

    masked_text, _mapping = anonymizer.mask_text(_input_text)

    # Handle output – file object (from main) vs string path (from auth dispatcher).
    if isinstance(args.output, str):
        if args.output == "-":
            sys.stdout.write(masked_text)
        else:
            Path(args.output).write_text(masked_text, encoding="utf-8")
    else:
        args.output.write(masked_text)

    return 0
