"""
Shared base for every ``llm-router`` top‑level CLI command.

A command is a self‑contained subtree of the top‑level parser.  The base owns
the two things that were previously copy‑pasted across ``auth`` / ``anonymizer``
/ ``config`` / ``util``:

* a **single parser source of truth** — built once and reused by both the
  top‑level dispatcher (:func:`llm_router_cli.cli.main`) and the standalone
  :meth:`run` entry point, so the two trees can never drift apart; and
* a **single dispatch path** — routing happens exclusively on the parsed
  ``argparse.Namespace`` (the raw ``argv`` is never re‑scanned).

Concrete commands set the class attributes :attr:`NAME`, :attr:`HELP` and
:attr:`SUBPARSER_DEST`, and implement :meth:`register_children` (declare the
leaf sub‑commands) and :meth:`dispatch` (route on the namespace).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, ClassVar, List, Optional


def _exit_code(exc: SystemExit) -> int:
    """Normalize an argparse ``SystemExit`` (``--help`` / errors) to an int."""
    code = exc.code
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    return 1


class BaseCommand:
    """Base class shared by all ``llm-router`` top‑level commands."""

    #: Command name (must match the value used under the top‑level parser).
    NAME: ClassVar[str] = ""
    #: Help text shown next to the command in the top‑level ``--help``.
    HELP: ClassVar[str] = ""
    #: ``dest`` for the command's own sub‑parsers (its namespace field).
    SUBPARSER_DEST: ClassVar[str] = "command"

    # ------------------------------------------------------------------ #
    # Shared argument helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def add_verbose(p: argparse.ArgumentParser) -> None:
        """Add the ``--verbose`` flag (DEBUG logging) to *p*."""
        p.add_argument(
            "--verbose",
            action="store_true",
            help="Enable verbose (DEBUG) logging of internal operations.",
        )

    # ------------------------------------------------------------------ #
    # Registration (single source of truth)
    # ------------------------------------------------------------------ #
    @classmethod
    def register(
        cls, subparsers: argparse._SubParsersAction[Any]
    ) -> argparse.ArgumentParser:
        """Add the command (and its children) under *subparsers*."""
        parser: argparse.ArgumentParser = subparsers.add_parser(
            cls.NAME, help=cls.HELP
        )
        cls._attach_children(parser)
        return parser

    @classmethod
    def _attach_children(cls, parser: argparse.ArgumentParser) -> None:
        """Attach this command's leaf sub‑commands to *parser*."""
        children = parser.add_subparsers(dest=cls.SUBPARSER_DEST)
        cls.register_children(children)

    @classmethod
    def register_children(cls, subparsers: argparse._SubParsersAction[Any]) -> None:
        """Declare this command's leaf sub‑commands under *subparsers*."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #
    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Route a parsed *args* namespace to the appropriate sub‑command."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Standalone entry point
    # ------------------------------------------------------------------ #
    @classmethod
    def run(cls, argv: Optional[List[str]] = None) -> int:
        """
        Parse *argv* with the standalone parser and dispatch the result.

        ``argv`` is the argument list *after* the program name; a redundant
        leading command name (e.g. ``["auth", "key", ...]``) is tolerated.
        """
        if argv is None:
            argv = sys.argv[1:]
        if argv and argv[0] == cls.NAME:
            argv = argv[1:]

        parser = cls.build_parser()
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return _exit_code(exc)
        return cls.dispatch(args)

    @classmethod
    def build_parser(cls) -> argparse.ArgumentParser:
        """Build the standalone parser for this command (single source of tree)."""
        parser = argparse.ArgumentParser(
            prog=f"llm-router {cls.NAME}",
            description=cls.HELP or None,
        )
        cls._attach_children(parser)
        return parser
