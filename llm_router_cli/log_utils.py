"""
Shared logging helpers for the ``llm-router util`` apps.

The util apps log at standard levels (``INFO`` for milestones, ``DEBUG`` for
per‑task / per‑LLM‑call detail).  Library consumers configure logging
themselves (standard practice); CLI entry points call :func:`setup_logging`
so that ``--verbose`` has one predictable meaning everywhere:

* without ``--verbose`` → ``INFO`` (progress bar + key milestones);
* with ``--verbose``    → ``DEBUG`` (what is sent, what comes back, timings).
"""

from __future__ import annotations

import logging

__all__ = ["setup_logging", "shorten"]

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(verbose: bool = False) -> None:
    """
    Configure the root logger for a CLI run.

    Idempotent: safe to call more than once (e.g. from both the top‑level
    dispatcher and a standalone entry point) — an existing handler is reused
    and only the effective level is adjusted.
    """
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        root.addHandler(handler)


def shorten(text: object, limit: int = 120) -> str:
    """
    Truncate *text* for compact, safe logging.

    Always returns a single line (embedded newlines collapsed) so one log
    record never spans multiple lines in a terminal or log file.
    """
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"
