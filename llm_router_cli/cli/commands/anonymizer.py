"""
Anonymiser subcommand for ``llm-router``.

Provides text anonymisation via pluggable algorithms.  Currently only the
``fast_masker`` algorithm is implemented; the ``pii`` algorithm is accepted on
the command line but reported as not yet implemented.

Typical usage::

    llm-router anonymizer run --algorithm fast_masker <input_file>
    echo "My phone is +48 123 456 789" \\
        | llm-router anonymizer run --algorithm fast_masker

Output is written to stdout by default; use ``--output`` / ``-o`` to direct it
to a file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, ClassVar, List, Tuple

from .base import BaseCommand


class AnonymizerCommand(BaseCommand):
    """Encapsulates the *anonymizer run* subcommand (parser, args and masking)."""

    NAME: ClassVar[str] = "anonymizer"
    HELP: ClassVar[str] = "Anonymise text using a selectable algorithm"
    SUBPARSER_DEST: ClassVar[str] = "anonymizer_command"

    RUN_NAME = "run"
    RUN_HELP = "Run text anonymisation"
    _ALGO_HELP = "Anonymization algorithm to use (pii is not yet implemented)"

    _DISABLE_FLAGS: List[Tuple[str, str]] = [
        ("phone", "phone-number anonymisation"),
        ("url", "URL anonymisation"),
        ("ip", "IP-address anonymisation"),
        ("pesel", "PESEL anonymisation"),
        ("email", "e-mail anonymisation"),
    ]

    # ---- Argument definitions ------------------------------------------- #
    @classmethod
    def _add_run_args(cls, p: argparse.ArgumentParser) -> None:
        """Add the standard ``anonymizer run`` arguments to *p*."""
        p.add_argument(
            "--algorithm",
            required=True,
            choices=["fast_masker", "pii"],
            help=cls._ALGO_HELP,
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
        for flag, desc in cls._DISABLE_FLAGS:
            p.add_argument(
                f"--disable-{flag}",
                action="store_true",
                help=f"Do not apply {desc}.",
            )

    # ---- Registration ---------------------------------------------------- #
    @classmethod
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the *run* sub-subcommand under *subparsers*."""
        run_parser = subparsers.add_parser(cls.RUN_NAME, help=cls.RUN_HELP)
        cls._add_run_args(run_parser)

    # ---- Dispatch -------------------------------------------------------- #
    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Route on the parsed namespace (no re-parsing of ``argv``)."""
        if getattr(args, cls.SUBPARSER_DEST, None) != cls.RUN_NAME:
            cls.build_parser().print_help()
            return 0
        return cls._mask(args)

    # ---- Core masking logic --------------------------------------------- #
    @classmethod
    def _mask(cls, args: argparse.Namespace) -> int:
        """Core masking logic shared by the ``run`` subcommand."""
        algorithm = args.algorithm

        if algorithm == "pii":
            print(
                "Error: 'pii' algorithm is not yet implemented. "
                "Use '--algorithm fast_masker' instead.",
                file=sys.stderr,
            )
            return 1

        # Import lazily to avoid pulling in the plugin package at module load
        # time. ``llm_router_plugins`` ships no type stubs (see mypy.ini).
        from llm_router_plugins.maskers.fast_masker.core.masker import (
            EmailRule,
            FastMasker,
            IpRule,
            PhoneRule,
            PeselRule,
            UrlRule,
        )

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

        # Handle input.
        if isinstance(args.input, str):
            input_text = (
                sys.stdin.read()
                if args.input == "-"
                else Path(args.input).read_text(encoding="utf-8")
            )
        else:  # pragma: no cover - pre-parsed file handle (library use)
            input_text = args.input.read()

        masked_text, _mapping = anonymizer.mask_text(input_text)

        # Handle output.
        if isinstance(args.output, str):
            if args.output == "-":
                sys.stdout.write(masked_text)
            else:
                Path(args.output).write_text(masked_text, encoding="utf-8")
        else:  # pragma: no cover - pre-parsed file handle (library use)
            args.output.write(masked_text)

        return 0
