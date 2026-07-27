"""
Anonymiser subcommand for ``llm-router auth``.

Provides text anonymisation via pluggable algorithms.  Currently only the
``fast_masker`` algorithm is implemented; the ``pii`` algorithm will be added
in a future release.

Typical usage::

    llm-router auth anonymizer run --algorithm fast_masker <input_file>
    echo "My phone is +48 123 456 789" \\
        | llm-router auth anonymizer run --algorithm fast_masker

Output is written to stdout by default; use ``--output`` / ``-o`` to direct it
to a file.
"""

from __future__ import annotations

import sys
import argparse

from pathlib import Path


class AnonymizerCommand:
    """Encapsulates the *anonymizer run* subcommand.

    This class owns all argument definitions, parsing, and masking logic
    for the anonymiser so that no module-level ``_`` functions leak out
    of this file.

    Public API (exactly two methods):
      - :meth:`register_parser`  – register *anonymizer run* under a parent argparse parser.
      - :meth:`run`             – standalone entry point; parse + mask.
    """

    NAME = "anonymizer"
    RUN_NAME = "run"
    HELP_TEXT = "Run text anonymisation"

    # ---- Argument definitions (class-level constants) ----------------------

    _ALGO_HELP = "Anonymisation algorithm to use (pii is not yet implemented)"

    _DISABLE_FLAGS: list[tuple[str, str]] = [
        ("phone", "phone-number anonymisation"),
        ("url", "URL anonymisation"),
        ("ip", "IP-address anonymisation"),
        ("pesel", "PESEL anonymisation"),
        ("email", "e-mail anonymisation"),
    ]

    # ---- Argument-adding helper --------------------------------------------

    @staticmethod
    def _add_common_args(p: argparse.ArgumentParser) -> None:
        """
        Add the standard ``anonymizer run`` arguments to *p*.
        """
        p.add_argument(
            "--algorithm",
            required=True,
            choices=["fast_masker", "pii"],
            help=AnonymizerCommand._ALGO_HELP,
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
        for flag, desc in AnonymizerCommand._DISABLE_FLAGS:
            p.add_argument(
                f"--disable-{flag}",
                action="store_true",
                help=f"Do not apply {desc}.",
            )

    # ---- Registration ------------------------------------------------------

    @classmethod
    def register_parser(
        cls,
        parser: argparse.ArgumentParser | argparse._SubParsersAction,
    ) -> None:
        """Register the *anonymizer run* sub-subparser under a parent.

        Parameters
        ----------
        parser : argparse.ArgumentParser | argparse._SubParsersAction
            Either a **subparsers action** (nested registration — just adds
            ``run`` and its arguments) or a **flat parser** for standalone
            invocation (configures it directly).
        """
        if isinstance(parser, argparse._SubParsersAction):
            run_parser = parser.add_parser(cls.RUN_NAME, help=cls.HELP_TEXT)
        else:
            run_parser = parser

        cls._add_common_args(run_parser)

    # ---- Public run() entry point ------------------------------------------

    @classmethod
    def run(cls, argv: list[str] | None = None) -> int:
        """Execute the anonymizer ``run`` subcommand.

        Parameters
        ----------
        argv : list[str] | None
            Raw command-line arguments (not including "anonymizer").
        Returns
        -------
        int
            Exit code (0 = success, 1 = error).
        """
        if argv is None:
            argv = []
        if argv and argv[0] == "run":
            argv = argv[1:]

        p = argparse.ArgumentParser(
            prog="llm-router auth anonymizer",
            description="Run text anonymisation with a selected algorithm.",
        )
        cls._add_common_args(p)
        args = p.parse_args(argv)
        return cls._mask(args)

    # ---- Core masking logic ------------------------------------------------

    @classmethod
    def _handle_anonymizer_from_args(cls, args) -> int:  # noqa: C901
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
        return cls._mask(args)

    @classmethod
    def _mask(cls, args) -> int:  # noqa: C901
        """Core masking logic shared by :meth:`run` and :meth:`_handle_anonymizer_from_args`.

        Handles two calling conventions:
          - :meth:`run` (standalone): input/output are string paths ("-" means stdin/stdout).
          - auth dispatcher (_handle_anonymizer_from_args): same as above.
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
            _input_text = (
                sys.stdin.read()
                if args.input == "-"
                else Path(args.input).read_text(encoding="utf-8")
            )
        else:
            _input_text = args.input.read()

        masked_text, _mapping = anonymizer.mask_text(_input_text)

        # Handle output.
        if isinstance(args.output, str):
            if args.output == "-":
                sys.stdout.write(masked_text)
            else:
                Path(args.output).write_text(masked_text, encoding="utf-8")
        else:
            args.output.write(masked_text)

        return 0
