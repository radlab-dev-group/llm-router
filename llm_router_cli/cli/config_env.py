"""
The per-instance ``config.env`` file: parsing, scaffolding and updating.

``~/.llm-router/instances/<name>/config.env`` holds ``KEY=value`` overrides
that survive a ``server stop`` / ``server start`` cycle, so an instance keeps
its port, models config or load-balancing strategy without repeating the whole
command line. Precedence is: CLI flag > ``config.env`` > shell env >
:data:`~llm_router_cli.cli.env_defaults.DEFAULT_ENV`.

:func:`update_config_env` is the write side of that promise (used by
``server start --save-config``): it rewrites a key in place, keeps hand-written
comments and ordering, and never touches unrelated variables.
"""

from __future__ import annotations

import os
import re
import sys

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from llm_router_cli.cli.env_defaults import DEFAULT_ENV
from llm_router_lib.core.constants import ENV_PREFIX


def _strip_quotes(value: str) -> str:
    """Drop one matching pair of single/double quotes around *value*."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_env_file(path: Path) -> Dict[str, str]:
    """
    Parse a simple ``KEY=value`` file (``config.env``) into a dict.

    Blank lines and ``#`` comments are skipped, a leading ``export`` is
    tolerated, values may be quoted, ``~`` is expanded, and ``KEY=`` yields
    an empty value. Malformed lines and non-``LLM_ROUTER_*`` keys are
    reported on stderr but never abort the command.
    """
    values: Dict[str, str] = {}
    path = Path(path)
    if not path.is_file():
        return values
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Warning: cannot read {path}: {exc}", file=sys.stderr)
        return values

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, separator, value = line.partition("=")
        if not separator:
            print(
                f"Warning: ignoring {path}:{lineno} (no '=' in {line!r})",
                file=sys.stderr,
            )
            continue
        key = key.strip()
        if not key:
            print(
                f"Warning: ignoring {path}:{lineno} (empty variable name)",
                file=sys.stderr,
            )
            continue
        if not key.startswith(ENV_PREFIX):
            print(
                f"Warning: ignoring {path}:{lineno} "
                f"(key {key!r} is not an {ENV_PREFIX}* variable)",
                file=sys.stderr,
            )
            continue
        values[key] = os.path.expanduser(_strip_quotes(value.strip()))
    return values


def apply_instance_config(values: Dict[str, str]) -> None:
    """Export *values* into the current process environment."""
    for key, value in values.items():
        os.environ[key] = value


def scaffold_config_env(path: Path, name: str) -> bool:
    """
    Create a commented ``config.env`` template for a new instance.

    An existing file is never touched; returns True only when created.
    """
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Per-instance configuration for the 'llm-router server' command.\n"
        f"# Instance: {name}\n"
        "#\n"
        "# One KEY=value per line; '#' starts a comment. Only variables named\n"
        f"# {ENV_PREFIX}... are applied (anything else is ignored).\n"
        "# Precedence: CLI flag > this file > shell environment > built-in\n"
        "# defaults.\n"
        "#\n"
        "# Examples (uncomment to use):\n"
        "# LLM_ROUTER_SERVER_PORT=8081\n"
        "# LLM_ROUTER_SERVER_HOST=127.0.0.1\n"
        f"# LLM_ROUTER_MODELS_CONFIG={DEFAULT_ENV['LLM_ROUTER_MODELS_CONFIG']}\n"
        "# LLM_ROUTER_SERVER_WORKERS_COUNT=2\n"
        "# LLM_ROUTER_LOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )
    return True


#: Characters that may be written into ``config.env`` without quoting.
_UNQUOTED_ENV_VALUE_RE = re.compile(r"^[A-Za-z0-9_./:+,@=%^-]*$")
#: Find a key's existing line: first an active assignment, then a commented
#: template entry (so ``--save-config`` uncomments the template in place).
_ACTIVE_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_COMMENTED_ENV_LINE_RE = re.compile(
    r"^\s*#\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*="
)


def format_env_value(value: str) -> Optional[str]:
    """
    Render *value* as the right-hand side of a ``config.env`` line.

    Simple values are written bare so the file stays hand-editable; anything
    else is quoted with the one quote character it does not contain. ``None``
    means "cannot be represented" (an embedded newline, or both quote kinds)
    and such a value is never written to the file.
    """
    if _UNQUOTED_ENV_VALUE_RE.match(value):
        return value
    if "\n" in value or "\r" in value:
        return None
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return None


def update_config_env(
    path: Path, values: Dict[str, str]
) -> Tuple[List[str], List[str]]:
    """
    Merge *values* into a ``config.env`` file, keeping everything else intact.

    A key that already has a line — active, or commented out in the scaffolded
    template — is rewritten exactly where it stands, so hand-written comments,
    ordering and unrelated variables survive; unknown keys are appended. The
    file gets mode 0600, as it may hold Redis passwords.

    Returns the ``(changed, unchanged)`` key lists: a key whose rendered line
    is already there counts as unchanged, which makes repeating the same
    ``server start --save-config`` idempotent. Raises :exc:`OSError` when the
    file cannot be read or written, and :exc:`ValueError` for a value
    :func:`format_env_value` cannot render.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = text.splitlines()

    changed: List[str] = []
    unchanged: List[str] = []
    for key, value in values.items():
        rendered = format_env_value(value)
        if rendered is None:
            raise ValueError(f"{key}: value cannot be written to {path}")
        line = f"{key}={rendered}"
        target = -1
        for index, current in enumerate(lines):
            active = _ACTIVE_ENV_LINE_RE.match(current)
            if active:
                if active.group(1) == key:
                    target = index
                    break
                continue
            commented = _COMMENTED_ENV_LINE_RE.match(current)
            if commented and commented.group(1) == key and target < 0:
                target = index
        if target >= 0:
            if lines[target] == line:
                unchanged.append(key)
                continue
            lines[target] = line
        else:
            lines.append(line)
        changed.append(key)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return changed, unchanged
