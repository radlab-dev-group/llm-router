"""
Server lifecycle subcommands for ``llm-router``.

Wraps the REST API entry point (``python -m llm_router_api.rest_api``) in a
managed background daemon with a PID file, so the same lifecycle operations
``run-rest-api-gunicorn.sh`` performs can be driven from the CLI::

    llm-router server start    # start in the background (daemon, PID file)
    llm-router server status   # show whether the server is running
    llm-router server log      # follow the log (tail -f style, colored levels)
    llm-router server stop    # SIGTERM (with grace period), or SIGKILL --force
    llm-router server reload  # stop the running server, then start it again
    llm-router server list     # list every known instance (--json for scripts)
    llm-router server rm-instance NAME  # drop a named instance's state

Several instances can run side by side: ``-i/--instance NAME`` (or
``$LLM_ROUTER_INSTANCE``) gives each one its own state tree under
``~/.llm-router/instances/NAME`` (PID file, run record, daemon log,
``config.env`` overrides, metrics dir, application log). ``stop --all`` and
``status --all`` act on every instance at once. The built-in ``default``
instance keeps the historical single-instance layout in ``~/.llm-router``.

Unless the user's environment already defines them, the command applies the
same ``LLM_ROUTER_*`` defaults as ``run-rest-api-gunicorn.sh``.
"""

# The module owns the whole lifecycle of one command (start / stop / reload /
# status / log / list / rm-instance) and its on-disk state format, so it is
# deliberately kept in one place.
# pylint: disable=too-many-lines

from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, FrozenSet, IO, List, Optional, Tuple

from llm_router_cli.cli.commands.base import BaseCommand
from llm_router_cli.cli.config_env import (
    apply_instance_config,
    format_env_value,
    parse_env_file,
    scaffold_config_env,
    update_config_env,
)
from llm_router_cli.cli.env_defaults import (
    apply_default_env,
    collect_env,
    DEFAULT_LOG_FILENAME,
)

#: Per-user state directory (same home location as ``memory-keys.json``).
_STATE_DIR = BaseCommand.STATE_DIR
DEFAULT_PID_FILE = _STATE_DIR / "server.pid"
DEFAULT_LOG_FILE = _STATE_DIR / "server.log"


#: Name of the legacy single-instance layout: its state stays directly in
#: ``~/.llm-router`` (``server.pid`` / ``server.pid.run`` / ``server.log``).
DEFAULT_INSTANCE = "default"

#: Environment variable read when ``--instance`` is not given, so a shell
#: session (or a systemd unit) can pin every command to one instance.
INSTANCE_ENV_VAR = "LLM_ROUTER_INSTANCE"

#: Instance names are used verbatim as state-directory names, so they are
#: restricted to a filesystem-safe slug (no separators, no ``..``).
_INSTANCE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: Directory (under ``_STATE_DIR``) holding every named instance's state tree.
_INSTANCES_DIRNAME = "instances"

#: Per-instance lock guarding concurrent ``start`` calls (PID-file creation
#: is not atomic with the ``is it alive?`` check).
_START_LOCK_SUFFIX = "server.start.lock"

#: A start lock older than this is treated as abandoned (a killed ``start``)
#: and broken, so an instance never stays wedged by a crashed CLI run.
_START_LOCK_TIMEOUT_SECONDS = 60

#: Per-instance overrides file, applied between the shell env and the defaults.
_CONFIG_ENV_FILENAME = "config.env"


def instances_dir() -> Path:
    """Return the root of the named-instance state trees."""
    return _STATE_DIR / _INSTANCES_DIRNAME


# -------------------------------------------------------------------------- #
# Instances (one state tree per concurrently running server)
# -------------------------------------------------------------------------- #
@dataclass(frozen=True)
class InstancePaths:
    """Filesystem layout of a single router instance."""

    name: str
    dir: Path
    pid_file: Path
    run_file: Path
    daemon_log: Path
    config_env: Path
    metrics_dir: Path
    #: The application's own log inside the instance dir (``None`` for the
    #: ``default`` instance, which keeps the CWD-relative historical behavior).
    app_log: Optional[Path]
    lock_file: Path

    @property
    def named(self) -> bool:
        """True for every instance except the legacy ``default`` one."""
        return self.name != DEFAULT_INSTANCE

    def ensure_dir(self) -> None:
        """Create the instance state directory (parents included)."""
        self.dir.mkdir(parents=True, exist_ok=True)


def instance_name_from(args: argparse.Namespace) -> str:
    """Resolve the instance name from ``--instance``, env, or the default."""
    name = getattr(args, "instance", None)
    if not name:
        name = os.environ.get(INSTANCE_ENV_VAR)
    return name or DEFAULT_INSTANCE


def resolve_instance(args: argparse.Namespace) -> InstancePaths:
    """
    Build the :class:`InstancePaths` for *args*.

    ``default`` maps onto the historical ``~/.llm-router`` layout so existing
    PID files, scripts and muscle memory keep working; every other name gets
    its own ``~/.llm-router/instances/<name>`` directory (PID file, run
    record, daemon log, ``config.env``, metrics dir and application log).

    Raises:
        ValueError: if the name is not a filesystem-safe slug.
    """
    name = instance_name_from(args)
    if not _INSTANCE_NAME_RE.match(name) or ".." in name:
        raise ValueError(
            f"invalid instance name {name!r}: use 1-64 characters from "
            "letters, digits, '.', '_' or '-' (starting with a letter or "
            "digit), e.g. 'llm-router server start -i dev'"
        )

    if name == DEFAULT_INSTANCE:
        return InstancePaths(
            name=name,
            dir=_STATE_DIR,
            pid_file=DEFAULT_PID_FILE,
            run_file=run_file_for(DEFAULT_PID_FILE),
            daemon_log=DEFAULT_LOG_FILE,
            config_env=_STATE_DIR / _CONFIG_ENV_FILENAME,
            metrics_dir=_STATE_DIR / "metrics" / "prometheus" / "multiproc",
            app_log=None,
            lock_file=_STATE_DIR / _START_LOCK_SUFFIX,
        )

    inst_dir = instances_dir() / name
    pid_file = inst_dir / "server.pid"
    return InstancePaths(
        name=name,
        dir=inst_dir,
        pid_file=pid_file,
        run_file=run_file_for(pid_file),
        daemon_log=inst_dir / "server.log",
        config_env=inst_dir / _CONFIG_ENV_FILENAME,
        metrics_dir=inst_dir / "metrics" / "prometheus" / "multiproc",
        app_log=inst_dir / DEFAULT_LOG_FILENAME,
        lock_file=inst_dir / _START_LOCK_SUFFIX,
    )


def check_port_free(host: str, port: int) -> Optional[str]:
    """
    Return an error message when *port* cannot be bound, else ``None``.

    Two instances on one host must not share a port; binding probes it once
    before any daemon is spawned, so the second ``start`` fails loudly and
    immediately instead of dying silently in the background.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host or "0.0.0.0", int(port)))
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.EADDRINUSE:
            return f"port {port} is already in use on {host or '0.0.0.0'}"
        print(f"Warning: could not verify port availability: {exc}", file=sys.stderr)
        return None
    finally:
        probe.close()
    return None


def _remove_quietly(path: Path) -> None:
    """Delete *path* if present, ignoring every error."""
    try:
        Path(path).unlink()
    except OSError:
        pass


def acquire_start_lock(instance: InstancePaths) -> Optional[Path]:
    """
    Take the per-instance start lock; return its path or ``None`` if busy.

    A lock left behind by a killed ``start`` is broken after
    :data:`_START_LOCK_TIMEOUT_SECONDS` so the instance is not stuck forever.
    """
    instance.ensure_dir()
    lock_file = instance.lock_file
    for attempt in (0, 1):
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if attempt:
                return None
            try:
                age = time.time() - lock_file.stat().st_mtime
            except OSError:
                continue
            if age <= _START_LOCK_TIMEOUT_SECONDS:
                return None
            _remove_quietly(lock_file)
            continue
        except OSError as exc:
            print(f"Warning: cannot create {lock_file}: {exc}", file=sys.stderr)
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
        return lock_file
    return None


def release_start_lock(lock_file: Optional[Path]) -> None:
    """Release the start lock held by :func:`acquire_start_lock`."""
    if lock_file is not None:
        _remove_quietly(lock_file)


def discover_instances() -> List[InstancePaths]:
    """
    Return every instance that has state on disk (running or not).

    The legacy ``default`` instance counts as discovered only while its PID or
    run record exists (otherwise it is just the shared state directory, not an
    instance the user created). A named instance also survives on disk with
    only its ``config.env``, so deleting its PID file does not lose it.
    """
    found: List[InstancePaths] = []
    default = resolve_instance(argparse.Namespace())
    if default.pid_file.exists() or default.run_file.exists():
        found.append(default)

    root = instances_dir()
    try:
        children = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        children = []
    for child in children:
        name = child.name
        if not _INSTANCE_NAME_RE.match(name) or ".." in name:
            continue
        instance = resolve_instance(argparse.Namespace(instance=name))
        if (
            instance.pid_file.exists()
            or instance.run_file.exists()
            or instance.config_env.exists()
        ):
            found.append(instance)
    return sorted(found, key=lambda item: item.name)


#: How long to wait for SIGTERM before telling the user to use ``--force``.
_STOP_GRACE_SECONDS = 15
_STOP_POLL_INTERVAL = 0.2
_KILL_POLL_SECONDS = 5
#: How long a freshly spawned daemon has to stay alive before we trust it.
_DAEMON_START_GRACE = 1.5


# -------------------------------------------------------------------------- #
# PID-file helpers
# -------------------------------------------------------------------------- #
def read_pid_file(path: Path) -> Optional[int]:
    """Return the PID stored in *path*, or ``None`` if missing/corrupt."""
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pid_file(path: Path, pid: int) -> None:
    """Write *pid* to *path*, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n", encoding="utf-8")


def remove_pid_file(path: Path) -> None:
    """Remove *path* if it exists (missing files are not an error)."""
    try:
        Path(path).unlink()
    except OSError:
        pass


def pid_alive(pid: int) -> bool:
    """True if a process with *pid* exists and is owned by us/someone."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def get_alive_pid(path: Path) -> Optional[int]:
    """
    Return the live PID from *path*; clean up and return ``None`` otherwise.

    A stale PID file (dead process) is removed so the next ``start`` succeeds.
    """
    pid = read_pid_file(path)
    if pid is None or pid <= 0:
        remove_pid_file(path)
        return None
    if not pid_alive(pid):
        remove_pid_file(path)
        return None
    return pid


def _wait_for_pid(path: Path, timeout: float = 5.0) -> Optional[int]:
    """Wait up to *timeout* seconds for a live PID to appear in *path*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = read_pid_file(path)
        if pid is not None and pid_alive(pid):
            return pid
        time.sleep(0.1)
    return None


def _wait_gone(pid: int, timeout: float) -> bool:
    """Wait up to *timeout* seconds for *pid* to disappear; True if gone."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(_STOP_POLL_INTERVAL)
    return not pid_alive(pid)


# -------------------------------------------------------------------------- #
# Run-record helpers (``<pidfile>.run`` next to the PID file)
# -------------------------------------------------------------------------- #
def run_file_for(pid_file: Path) -> Path:
    """Return the run-record path derived from *pid_file* (e.g. ``server.pid.run``)."""
    pid_file = Path(pid_file)
    return pid_file.parent / (pid_file.name + ".run")


def write_run_file(path: Path, record: Dict[str, Any]) -> None:
    """Write *record* as pretty-printed JSON to *path*."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def read_run_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load the run record from *path*; ``None`` if missing or corrupt."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def resolve_app_log_path(env: Dict[str, Any]) -> str:
    """
    Absolute path of the application's own (rotating) log file.

    ``LLM_ROUTER_LOG_FILENAME`` is often just a file name with no directory
    part; the server then creates it in the CWD from which it was launched,
    so the recorded path must be anchored to :func:`Path.cwd` to point at the
    real file.
    """
    name = env.get("LLM_ROUTER_LOG_FILENAME") or DEFAULT_LOG_FILENAME
    return anchor_log_name(name)


def anchor_log_name(name: str) -> str:
    """Anchor a bare log file name to the CWD; keep absolute paths as-is."""
    path = Path(name).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return str(path)


def resolve_instance_app_log(
    instance: InstancePaths, value: Optional[str], create: bool = True
) -> str:
    """
    Anchor the application-log *value* inside *instance*'s state directory.

    A named instance must never share its application log with another one.
    Launch scripts usually export a bare ``LLM_ROUTER_LOG_FILENAME`` (just
    ``llm-router.log``), which the server resolves against its CWD: every
    instance started from the same directory would then append to one file,
    where two rotating handlers truncate each other and silently lose entries.

    Absolute paths and ``~``-relative ones are honored as given; a relative
    value (bare file name or with subdirectories) is placed under
    :attr:`InstancePaths.dir`, with ``.``/``..`` components dropped so it
    cannot escape the instance tree. An empty *value* selects the instance's
    own default log name. *create* also creates the parent directory.
    """
    fallback = instance.app_log or Path(DEFAULT_LOG_FILENAME)
    if value is None or not str(value).strip():
        path = fallback
    else:
        candidate = Path(str(value)).expanduser()
        if candidate.is_absolute():
            path = candidate
        else:
            parts = [part for part in candidate.parts if part not in (".", "..")]
            path = instance.dir.joinpath(*parts) if parts else fallback
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def resolve_models_config_path(env: Dict[str, Any]) -> str:
    """
    Absolute path of the models configuration file.

    ``LLM_ROUTER_MODELS_CONFIG`` is often a path relative to the launch CWD
    (e.g. ``resources/configs/models-config.json``); the server loads it
    from there, so the recorded path is anchored to :func:`Path.cwd`.
    Empty string when the variable is unset.
    """
    name = env.get("LLM_ROUTER_MODELS_CONFIG") or ""
    if not name:
        return ""
    return anchor_log_name(name)


def resolve_start_log_file(
    cli_value: Optional[str],
    shell_log_filename: Optional[str],
    default_log: Optional[Path] = None,
) -> Path:
    """
    Resolve the daemon log file for ``start``.

    An explicit ``--log-file`` wins. Otherwise, if the user exported
    ``LLM_ROUTER_LOG_FILENAME``, that path is used — a bare file name is
    anchored to the CWD, where the server process actually writes its log.
    Only when the variable is unset do we fall back to the per-user default
    under ``~/.llm-router``. ``shell_log_filename`` must be captured *before*
    :func:`apply_default_env` fills in the ``DEFAULT_ENV`` value.

    *default_log* replaces that fallback for named instances, whose daemon log
    lives inside their own state directory.
    """
    if cli_value:
        return Path(cli_value).expanduser()
    if shell_log_filename:
        return Path(anchor_log_name(shell_log_filename))
    if default_log is not None:
        return Path(default_log)
    return DEFAULT_LOG_FILE


def log_file_for(
    args: argparse.Namespace,
    instance: InstancePaths,
    shell_log_filename: Optional[str] = None,
) -> Path:
    """
    Resolve the daemon log for *instance*.

    A named instance never follows the shell's ``LLM_ROUTER_LOG_FILENAME``:
    that variable names the *application's* log, which for a named instance
    lives inside its own state directory. Only the ``default`` instance keeps
    the historical behavior of honoring the shell variable.
    """
    return resolve_start_log_file(
        args.log_file,
        None if instance.named else shell_log_filename,
        instance.daemon_log if instance.named else None,
    )


# -------------------------------------------------------------------------- #
# Daemonization
# -------------------------------------------------------------------------- #
def _redirect_stdio(log_file: Path) -> None:
    """Point stdin at /dev/null and stdout/stderr at *log_file* (append)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()

    log_fd = os.open(str(log_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    devnull_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull_fd, sys.stdin.fileno())
    os.dup2(log_fd, sys.stdout.fileno())
    os.dup2(log_fd, sys.stderr.fileno())
    os.close(devnull_fd)
    if log_fd > 2:
        os.close(log_fd)


# -------------------------------------------------------------------------- #
# Log tailing / colorization
# -------------------------------------------------------------------------- #
_LOG_LEVEL_RE = re.compile(
    r"\b(TRACE|DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b"
)

_ANSI_COLORS = {
    "TRACE": "\033[35m",
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "WARN": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[1;31m",
    "FATAL": "\033[1;31m",
}
_ANSI_RESET = "\033[0m"


def colorize_line(line: str, color: str) -> str:
    """
    Wrap *line* in the ANSI color of its log level, if it has one.

    ``color`` is ``"always"`` or ``"never"``; lines without a recognizable
    level token are returned unchanged.
    """
    if color == "never":
        return line
    match = _LOG_LEVEL_RE.search(line)
    if not match:
        return line
    code = _ANSI_COLORS.get(match.group(1))
    if code is None:
        return line
    return f"{code}{line}{_ANSI_RESET}"


def tail_lines(fh: IO[str], n: int) -> List[str]:
    """Return the last *n* lines of *fh* (rewinds *fh* to the start)."""
    if n <= 0:
        fh.seek(0)
        return []
    return list(deque(fh, maxlen=n))


# -------------------------------------------------------------------------- #
# Colored status rendering
# -------------------------------------------------------------------------- #
def _resolve_color(mode: str) -> bool:
    """Decide whether to emit ANSI colors for a ``--color`` *mode* value.

    ``auto`` (default) colors only when stdout is a TTY, so piped output stays
    clean; ``always``/``never`` force the choice.
    """
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty()


def _paint(enabled: bool, code: str, text: str) -> str:
    """Wrap *text* in an ANSI *code* when *enabled* is true, else return as-is."""
    if not enabled:
        return text
    return f"\033[{code}m{text}{_ANSI_RESET}"


#: Env variable names whose *values* must never be echoed verbatim.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|credential|api[_-]?key)"
)


def _is_sensitive(key: str) -> bool:
    """True if *key* names a credential whose value should be masked."""
    return bool(_SENSITIVE_KEY_RE.search(key))


#: Placeholder printed in place of a masked secret value.
_MASKED = "****"

#: Spellings of a recorded boolean value that mean "on" / "off" when a run
#: record is turned back into ``start`` flags by ``reload``.
_TRUE_TOKENS = frozenset({"1", "true", "yes", "on"})
_FALSE_TOKENS = frozenset({"0", "false", "no", "off"})


# -------------------------------------------------------------------------- #
# Command
# -------------------------------------------------------------------------- #
class ServerCommand(BaseCommand):
    """Manage the LLM-Router REST API server (start / stop / reload / status / log)."""

    NAME: ClassVar[str] = "server"
    HELP: ClassVar[str] = (
        "Manage the LLM-Router REST API server "
        "(start/stop/reload/status/log/list/rm-instance)"
    )
    SUBPARSER_DEST: ClassVar[str] = "server_command"

    START_NAME = "start"
    STOP_NAME = "stop"
    RELOAD_NAME = "reload"
    STATUS_NAME = "status"
    LOG_NAME = "log"
    LIST_NAME = "list"
    RM_INSTANCE_NAME = "rm-instance"
    START_HELP = "Start the REST API server in the background (daemon)"
    STOP_HELP = "Stop the running REST API server"
    RELOAD_HELP = "Restart the server (stop it, then start it again)"
    STATUS_HELP = "Show server status (pid, log, launch parameters)"
    LOG_HELP = "Follow the server log (tail -f style, colorized levels)"
    LIST_HELP = "List all known server instances (running or not)"
    RM_INSTANCE_HELP = "Delete a named instance's state directory"

    #: (namespace attribute, environment variable, value converter) pairs
    #: applied when the corresponding flag is given to ``server start``.
    _ENV_OVERRIDES: ClassVar[List[Tuple[str, str, Optional[str]]]] = [
        ("models_config", "LLM_ROUTER_MODELS_CONFIG", None),
        ("debug", "LLM_ROUTER_IN_DEBUG", "str"),
        ("verbose", "LLM_ROUTER_VERBOSE", "str"),
        ("lb_strategy", "LLM_ROUTER_BALANCE_STRATEGY", None),
        ("default_lang", "LLM_ROUTER_DEFAULT_EP_LANGUAGE", None),
        ("auth", "LLM_ROUTER_AUTH_ENABLED", "bool"),
        ("redis_host", "LLM_ROUTER_REDIS_HOST", None),
        ("redis_port", "LLM_ROUTER_REDIS_PORT", "str"),
        ("redis_db", "LLM_ROUTER_REDIS_DB", "str"),
        ("redis_password", "LLM_ROUTER_REDIS_PASSWORD", None),
        ("auth_redis_host", "LLM_ROUTER_AUTH_REDIS_HOST", None),
        ("auth_redis_port", "LLM_ROUTER_AUTH_REDIS_PORT", "str"),
        ("auth_redis_db", "LLM_ROUTER_AUTH_REDIS_DB", "str"),
        ("auth_redis_password", "LLM_ROUTER_AUTH_REDIS_PASSWORD", None),
        # Bind target and engine, so ``--save-config`` can also remember where
        # (and how) an instance was last launched.
        ("server", "LLM_ROUTER_SERVER_TYPE", None),
        ("host", "LLM_ROUTER_SERVER_HOST", None),
        ("port", "LLM_ROUTER_SERVER_PORT", "str"),
    ]

    _LB_STRATEGIES = [
        "balanced",
        "weighted",
        "first_available",
        "first_available_optim",
    ]

    #: Engines accepted by ``start --server`` (also validated when ``reload``
    #: replays the flags of a previous launch).
    _SERVER_TYPES: ClassVar[List[str]] = ["gunicorn", "waitress", "flask"]

    #: ``start`` flags whose value argparse parses as an int.
    _NUMERIC_FLAGS: ClassVar[FrozenSet[str]] = frozenset(
        {
            "debug",
            "port",
            "redis_port",
            "redis_db",
            "auth_redis_port",
            "auth_redis_db",
        }
    )

    #: ``start`` flags that argparse restricts to ``0``/``1``.
    _BOOL_FLAGS: ClassVar[FrozenSet[str]] = frozenset({"debug", "auth"})

    #: Reverse of :attr:`_ENV_OVERRIDES` used by ``reload`` to rebuild the
    #: ``start`` command line from a run record:
    #: environment variable -> (flag, namespace attribute, converter).
    _RELOAD_FLAGS: ClassVar[Dict[str, Tuple[str, str, Optional[str]]]] = {
        env_key: (f"--{attr.replace('_', '-')}", attr, convert)
        for attr, env_key, convert in _ENV_OVERRIDES
    }

    # ---- Instance helpers ------------------------------------------------ #
    @classmethod
    def _instance(
        cls, args: argparse.Namespace
    ) -> Tuple[Optional[InstancePaths], Optional[str]]:
        """Resolve the target instance, or return the validation error."""
        try:
            return resolve_instance(args), None
        except ValueError as exc:
            return None, str(exc)

    @staticmethod
    def _pid_file_for(args: argparse.Namespace, instance: InstancePaths) -> Path:
        """Explicit ``--pid-file`` wins, else the instance's own PID file."""
        explicit = getattr(args, "pid_file", None)
        if explicit:
            return Path(explicit).expanduser()
        return instance.pid_file

    @staticmethod
    def _hint(command: str, instance: InstancePaths) -> str:
        """Render a copy-pasteable follow-up command for *instance*."""
        suffix = f" -i {instance.name}" if instance.named else ""
        return f"llm-router server {command}{suffix}"

    @staticmethod
    def _scope(instance: InstancePaths) -> str:
        """Suffix naming a non-default instance in error/hint messages."""
        return "" if not instance.named else f" for instance '{instance.name}'"

    @staticmethod
    def _all_conflict(args: argparse.Namespace) -> Optional[str]:
        """Error text when ``--all`` is combined with a single-target option."""
        if getattr(args, "all", False) and (
            getattr(args, "instance", None) or getattr(args, "pid_file", None)
        ):
            return "--all cannot be combined with --instance or --pid-file"
        return None

    @classmethod
    def _apply_start_env(
        cls, args: argparse.Namespace, instance: InstancePaths
    ) -> Optional[str]:
        """
        Build the environment a server for *instance* starts with.

        Order of application (last wins): built-in defaults, the shell
        environment, the instance ``config.env``, explicit CLI flags. Named
        instances additionally get their own application log and Prometheus
        multiproc directory, so concurrent instances cannot corrupt each
        other's metrics or logs. A named instance always gets its application
        log inside its state directory, even when the shell exported a bare
        ``LLM_ROUTER_LOG_FILENAME`` (which the server would otherwise resolve
        against the launch CWD and share with every sibling instance).

        Returns the user's own ``LLM_ROUTER_LOG_FILENAME`` (captured before the
        defaults were applied), which the daemon-log resolution still needs.
        """
        instance.ensure_dir()
        if instance.named:
            scaffold_config_env(instance.config_env, instance.name)
        apply_instance_config(parse_env_file(instance.config_env))

        user_log = os.environ.get("LLM_ROUTER_LOG_FILENAME")
        apply_default_env()
        # Explicit CLI flags win over both the defaults and the shell env.
        os.environ.update(cls.build_env_overrides(args))

        if instance.named:
            os.environ["LLM_ROUTER_LOG_FILENAME"] = resolve_instance_app_log(
                instance, user_log
            )
            if not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
                instance.metrics_dir.mkdir(parents=True, exist_ok=True)
                os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(instance.metrics_dir)
        return user_log

    @staticmethod
    def _warn_shared_app_log(instance: InstancePaths, log_path: str) -> None:
        """Warn (stderr, non-fatal) when another instance shares *log_path*.

        Only a hint: an explicit absolute ``LLM_ROUTER_LOG_FILENAME`` can
        deliberately point two instances at one file, but the usual cause is
        the two of them inheriting the same name and landing in the same
        directory, where their rotating handlers fight over the file.
        """
        if not instance.named or not log_path:
            return
        try:
            resolved = os.path.realpath(log_path)
            others = discover_instances()
        except OSError:  # pragma: no cover - defensive
            return
        for other in others:
            if other.name == instance.name:
                continue
            if get_alive_pid(other.pid_file) is None:
                continue
            other_log = (read_run_file(other.run_file) or {}).get("app_log_file")
            if not other_log:
                continue
            try:
                same_file = os.path.realpath(str(other_log)) == resolved
            except OSError:  # pragma: no cover - defensive
                same_file = False
            if same_file:
                print(
                    f"Warning: instance '{other.name}' is already logging to "
                    f"{log_path}; the two instances will interleave and rotate "
                    "the same file.",
                    file=sys.stderr,
                )
                return

    @staticmethod
    def _check_start_port(
        args: argparse.Namespace, instance: InstancePaths
    ) -> Optional[str]:
        """Pre-flight bind test of the port the server is about to use."""
        port_value = args.port
        if port_value is None:
            port_value = os.environ.get("LLM_ROUTER_SERVER_PORT")
        if port_value is None or str(port_value).strip() == "":
            return None
        try:
            port = int(port_value)
        except (TypeError, ValueError):
            return None
        host = args.host or os.environ.get("LLM_ROUTER_SERVER_HOST") or "0.0.0.0"
        error = check_port_free(host, port)
        if error is None:
            return None
        return (
            f"{error} (instance '{instance.name}').\n"
            "Use --port/--host or set LLM_ROUTER_SERVER_PORT in "
            f"{instance.config_env}."
        )

    @staticmethod
    def _models_config_source(
        args: argparse.Namespace,
        instance: InstancePaths,
        shell_models_config: Optional[str],
    ) -> str:
        """
        Name the layer that picked ``LLM_ROUTER_MODELS_CONFIG``.

        Called on the error path only, so parsing the instance ``config.env``
        (which warns on stderr about malformed lines) never costs a healthy
        start.
        """
        if getattr(args, "models_config", None):
            return "--models-config flag"
        if parse_env_file(instance.config_env).get("LLM_ROUTER_MODELS_CONFIG"):
            return f"config.env {instance.config_env}"
        if shell_models_config:
            return "shell environment"
        return "built-in default"

    @classmethod
    def _models_config_problem(cls, path: str) -> str:
        """
        Explain why the models config at *path* cannot be loaded, or ``""``.

        What is accepted mirrors how
        :meth:`llm_router_api.core.model_config.ModelConfig` reads the file: a
        JSON object whose sections are all empty is fine (that simply means
        "no models"), while one with any model defined must have an
        ``active_models`` section.
        """
        if not path:
            return "is not set"
        candidate = Path(path)
        if not candidate.exists():
            return "was not found"
        if not candidate.is_file():
            return "is not a file"
        try:
            with open(candidate, "rt", encoding="utf-8") as handle:
                data = json.load(handle)
        except OSError as exc:
            return f"cannot be read: {exc}"
        except json.JSONDecodeError as exc:
            return f"is not valid JSON: {exc}"
        if not isinstance(data, dict):
            return "must contain a JSON object"
        if (not data or any(data.values())) and "active_models" not in data:
            return "has no 'active_models' section"
        return ""

    @classmethod
    def _check_models_config(
        cls,
        args: argparse.Namespace,
        instance: InstancePaths,
        shell_models_config: Optional[str],
    ) -> Optional[str]:
        """
        Pre-flight check of the models config the server is about to load.

        A daemon publishes its PID *before* execing the server, so a missing
        or broken models config would otherwise be reported as a successful
        start with the real failure buried in the daemon log (see
        :meth:`_models_config_problem` for what counts as loadable).

        Returns the error text, or ``None`` when the server can start.
        """
        path = resolve_models_config_path(os.environ)
        reason = cls._models_config_problem(path)
        if not reason:
            return None

        source = cls._models_config_source(args, instance, shell_models_config)

        # Remove instance when no config is found
        cls._rm_instance(args=args, instance=instance)

        return (
            f"models config {reason}: "
            f"{path or 'LLM_ROUTER_MODELS_CONFIG'} (instance "
            f"'{instance.name}').\n"
            f"Source: {source}.\n"
            "Create the file, pass --models-config PATH, set "
            f"LLM_ROUTER_MODELS_CONFIG in {instance.config_env}, "
            "or use --no-config-check to start anyway."
        )

    @classmethod
    def _save_config(cls, args: argparse.Namespace, instance: InstancePaths) -> None:
        """
        Persist this command line's flags into the instance ``config.env``.

        Only flags actually given here are written (see
        :meth:`build_env_overrides`), so a later plain ``start -i NAME``
        relaunches the instance with the same settings. Values are stored
        verbatim — a Redis password included, which is why the file is kept
        mode 0600 — while only the *names* of the keys are echoed.

        Everything is best-effort: a state directory that cannot be written
        produces a warning, never a failed start.
        """
        overrides = cls.build_env_overrides(args)
        values: Dict[str, str] = {}
        for key, value in overrides.items():
            if format_env_value(value) is None:
                print(
                    f"Warning: not saving {key}: the value cannot be written "
                    f"to {instance.config_env}",
                    file=sys.stderr,
                )
                continue
            values[key] = value
        if not values:
            if not overrides:
                print(
                    "--save-config: nothing to save; only flags given on "
                    "this command line are persisted."
                )
            return
        try:
            scaffold_config_env(instance.config_env, instance.name)
            changed, unchanged = update_config_env(instance.config_env, values)
        except OSError as exc:
            print(
                f"Warning: cannot update {instance.config_env}: {exc}",
                file=sys.stderr,
            )
            return
        if changed:
            print(f"Saved {len(changed)} setting(s) to {instance.config_env}:")
            for key in changed:
                print(f"  {key}")
            if unchanged:
                print(f"  ({len(unchanged)} already up to date)")
        else:
            print(
                f"{instance.config_env} already up to date "
                f"({len(unchanged)} setting(s))"
            )

    # ---- Registration ---------------------------------------------------- #
    @classmethod
    def _add_pid_file_arg(cls, p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--pid-file",
            default=None,
            help=(
                "PID file location (default: the instance's own file, "
                f"{DEFAULT_PID_FILE} for the '{DEFAULT_INSTANCE}' instance)"
            ),
        )

    @classmethod
    def _add_instance_arg(cls, p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "-i",
            "--instance",
            metavar="NAME",
            default=None,
            help=(
                "Server instance to act on (default: "
                f"'{DEFAULT_INSTANCE}', or ${INSTANCE_ENV_VAR} when set). "
                "Each instance keeps its own state under "
                f"{instances_dir()}/<NAME>"
            ),
        )

    @classmethod
    def _add_color_arg(cls, p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--color",
            choices=["auto", "always", "never"],
            default="auto",
            help="Colorize output (auto = only on a TTY, default: %(default)s)",
        )

    @classmethod
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the server sub-commands (incl. list / rm-instance)."""
        start = subparsers.add_parser(cls.START_NAME, help=cls.START_HELP)
        start.add_argument(
            "--foreground",
            action="store_true",
            help="Run in the foreground instead of daemonizing (for debugging).",
        )
        start.add_argument(
            "--log-file",
            default=None,
            help=(
                "Daemon console log (default: LLM_ROUTER_LOG_FILENAME if set "
                "in the shell, else the instance's daemon log, "
                f"{DEFAULT_LOG_FILE} for the '{DEFAULT_INSTANCE}' instance). "
                "Not written in --foreground mode, where the server logs to "
                "the terminal; the application's own log always lives in the "
                "instance directory"
            ),
        )
        start.add_argument(
            "--server",
            choices=cls._SERVER_TYPES,
            default=None,
            help="WSGI server engine (default: LLM_ROUTER_SERVER_TYPE or gunicorn)",
        )
        start.add_argument("--host", default=None, help="Interface to bind to")
        start.add_argument("--port", type=int, default=None, help="Port number")
        start.add_argument(
            "--no-port-check",
            action="store_true",
            help="Skip the port-availability check before spawning.",
        )
        start.add_argument(
            "--no-config-check",
            action="store_true",
            help="Skip the models-config file check before spawning.",
        )
        start.add_argument(
            "--save-config",
            action="store_true",
            help=(
                "Save the flags given on this command line into the "
                "instance's config.env, so a later plain 'start' reuses "
                "them. Values are written verbatim (the file is kept mode "
                "0600); only key names are printed."
            ),
        )
        # Environment overrides (CLI flag > shell env > script defaults)
        start.add_argument(
            "--models-config",
            default=None,
            help="Models config JSON path (LLM_ROUTER_MODELS_CONFIG)",
        )
        start.add_argument(
            "--debug",
            type=int,
            choices=[0, 1],
            default=None,
            help="Enable (1) or disable (0) debug mode (LLM_ROUTER_IN_DEBUG)",
        )
        start.add_argument(
            "--verbose",
            action="store_const",
            const=1,
            default=None,
            help="Log raw, UNMASKED request params (LLM_ROUTER_VERBOSE). "
            "Never use in production: it prints PII to the log and "
            "delays the server startup.",
        )
        start.add_argument(
            "--lb-strategy",
            choices=cls._LB_STRATEGIES,
            default=None,
            help="Routing/balance strategy (LLM_ROUTER_BALANCE_STRATEGY)",
        )
        start.add_argument(
            "--default-lang",
            default=None,
            help=(
                "Default endpoint language, e.g. 'pl' "
                "(LLM_ROUTER_DEFAULT_EP_LANGUAGE)"
            ),
        )
        start.add_argument(
            "--auth",
            type=int,
            choices=[0, 1],
            default=None,
            help="Enable (1) or disable (0) API-key auth (LLM_ROUTER_AUTH_ENABLED)",
        )
        start.add_argument(
            "--redis-host", default=None, help="Redis host (LLM_ROUTER_REDIS_HOST)"
        )
        start.add_argument(
            "--redis-port",
            type=int,
            default=None,
            help="Redis port (LLM_ROUTER_REDIS_PORT)",
        )
        start.add_argument(
            "--redis-db",
            type=int,
            default=None,
            help="Redis DB index (LLM_ROUTER_REDIS_DB)",
        )
        start.add_argument(
            "--redis-password",
            default=None,
            help="Redis password (LLM_ROUTER_REDIS_PASSWORD)",
        )
        start.add_argument(
            "--auth-redis-host",
            default=None,
            help="Auth key-store Redis host (LLM_ROUTER_AUTH_REDIS_HOST)",
        )
        start.add_argument(
            "--auth-redis-port",
            type=int,
            default=None,
            help="Auth key-store Redis port (LLM_ROUTER_AUTH_REDIS_PORT)",
        )
        start.add_argument(
            "--auth-redis-db",
            type=int,
            default=None,
            help="Auth key-store Redis DB (LLM_ROUTER_AUTH_REDIS_DB)",
        )
        start.add_argument(
            "--auth-redis-password",
            default=None,
            help="Auth key-store Redis password (LLM_ROUTER_AUTH_REDIS_PASSWORD)",
        )
        cls._add_pid_file_arg(start)
        cls._add_instance_arg(start)

        stop = subparsers.add_parser(cls.STOP_NAME, help=cls.STOP_HELP)
        stop.add_argument(
            "--force",
            action="store_true",
            help="Skip the SIGTERM grace period and send SIGKILL instead.",
        )
        stop.add_argument(
            "--all",
            action="store_true",
            help="Stop every known instance instead of a single one.",
        )
        cls._add_pid_file_arg(stop)
        cls._add_instance_arg(stop)

        reload = subparsers.add_parser(cls.RELOAD_NAME, help=cls.RELOAD_HELP)
        reload.add_argument(
            "--force",
            action="store_true",
            help="Skip the SIGTERM grace period when stopping (send SIGKILL).",
        )
        reload.add_argument(
            "--graceful",
            action="store_true",
            help=(
                "Only send SIGHUP to the running master, so Gunicorn recycles "
                "its workers without a restart (no stop, no new process)."
            ),
        )
        cls._add_pid_file_arg(reload)
        cls._add_instance_arg(reload)

        status = subparsers.add_parser(cls.STATUS_NAME, help=cls.STATUS_HELP)
        cls._add_pid_file_arg(status)
        cls._add_instance_arg(status)
        cls._add_color_arg(status)
        status.add_argument(
            "--show-env",
            action="store_true",
            help="Show the environment section (hidden by default).",
        )
        status.add_argument(
            "--all",
            action="store_true",
            help="Report every known instance instead of a single one.",
        )

        log = subparsers.add_parser(cls.LOG_NAME, help=cls.LOG_HELP)
        log.add_argument(
            "--log-file",
            default=None,
            help=(
                "Explicit log file to follow. Default: the application's own "
                "log (LLM_ROUTER_LOG_FILENAME from the run record, or from "
                "the shell anchored to the instance directory for a named "
                f"instance); e.g. pass {DEFAULT_LOG_FILE} to follow the "
                "daemon's console log"
            ),
        )
        log.add_argument(
            "--lines",
            type=int,
            default=20,
            help="Number of initial lines to show, 0 for none (default: %(default)s)",
        )
        log.add_argument(
            "--no-follow",
            action="store_true",
            help="Show the initial tail and exit (no -f style following).",
        )
        cls._add_pid_file_arg(log)
        cls._add_color_arg(log)
        cls._add_instance_arg(log)

        instances = subparsers.add_parser(cls.LIST_NAME, help=cls.LIST_HELP)
        instances.add_argument(
            "--json",
            action="store_true",
            help="Print the instance list as JSON (for scripting).",
        )
        cls._add_color_arg(instances)

        rm_instance = subparsers.add_parser(
            cls.RM_INSTANCE_NAME, help=cls.RM_INSTANCE_HELP
        )
        rm_instance.add_argument(
            "name",
            help=(
                "Name of the instance to delete (its directory under "
                f"{instances_dir()})"
            ),
        )

    # ---- Dispatch -------------------------------------------------------- #
    @classmethod
    def build_env_overrides(cls, args: argparse.Namespace) -> Dict[str, str]:
        """
        Map explicitly-given ``start`` flags onto ``LLM_ROUTER_*`` variables.

        Unspecified flags (``None``) are skipped; given flags override the
        shell environment (CLI flag > shell env > script defaults).
        """
        overrides: Dict[str, str] = {}
        for attr, env_key, convert in cls._ENV_OVERRIDES:
            value = getattr(args, attr, None)
            if value is None:
                continue
            if convert == "bool":
                value = "true" if value else "false"
            elif convert is not None:
                value = str(value)
            overrides[env_key] = value
        return overrides

    @classmethod
    def build_run_record(
        cls,
        pid_file: Path,
        log_file: Path,
        cmd: List[str],
        args: argparse.Namespace,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Build the JSON record describing how the server was started.

        ``env`` holds *every* ``LLM_ROUTER_*`` variable in effect when the
        server was started (defaults + shell env + CLI overrides), i.e. the
        full configuration it runs with. ``env_overrides`` keeps just the
        CLI-flag-provided subset (see :meth:`build_env_overrides`).

        If *env* is ``None`` a live snapshot is taken via
        :func:`collect_env`; callers may pass an explicit mapping (e.g. tests).
        """
        if env is None:
            env = collect_env()
        return {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "executable": sys.executable,
            "command": cmd,
            "server": os.environ.get("LLM_ROUTER_SERVER_TYPE", "gunicorn"),
            "instance": instance_name_from(args),
            "log_file": str(log_file),
            "app_log_file": resolve_app_log_path(env),
            "models_config": resolve_models_config_path(env),
            "pid_file": str(pid_file),
            "env": env,
            "env_overrides": cls.build_env_overrides(args),
        }

    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Route on the parsed namespace (no re-parsing of ``argv``)."""
        action = getattr(args, cls.SUBPARSER_DEST, None)
        if action == cls.START_NAME:
            return cls._start(args)
        if action == cls.STOP_NAME:
            return cls._stop(args)
        if action == cls.RELOAD_NAME:
            return cls._reload(args)
        if action == cls.STATUS_NAME:
            return cls._status(args)
        if action == cls.LOG_NAME:
            return cls._log(args)
        if action == cls.LIST_NAME:
            return cls._list(args)
        if action == cls.RM_INSTANCE_NAME:
            return cls._rm_instance(args)
        return cls.show_help(0)

    # ---- Actions --------------------------------------------------------- #
    @classmethod
    def _start(cls, args: argparse.Namespace) -> int:
        """Start the API server (daemonized by default)."""
        instance, error = cls._instance(args)
        if error:
            return cls.fail(error)
        assert instance is not None
        pid_file = cls._pid_file_for(args, instance)

        alive = get_alive_pid(pid_file)
        if alive is not None:
            return cls.fail(
                f"a server is already running{cls._scope(instance)} "
                f"(pid={alive}, "
                f"pid file: {pid_file}).\n"
                f"Use '{cls._hint('reload', instance)}' or "
                f"'{cls._hint('stop', instance)}'."
            )

        # The lock closes the race between "is it alive?" and "write the PID":
        # two concurrent ``start`` calls for one instance must not both spawn.
        lock = acquire_start_lock(instance)
        if lock is None:
            return cls.fail(
                f"a start is already in progress for instance "
                f"'{instance.name}'; retry in a moment"
            )
        try:
            # Captured before the defaults land in os.environ, so the error
            # message can still name the layer the value really came from.
            shell_models_config = os.environ.get("LLM_ROUTER_MODELS_CONFIG")
            shell_log_filename = cls._apply_start_env(args, instance)
            cls._warn_shared_app_log(
                instance, os.environ.get("LLM_ROUTER_LOG_FILENAME", "")
            )

            if not args.no_config_check:
                config_error = cls._check_models_config(
                    args, instance, shell_models_config
                )
                if config_error is not None:
                    return cls.fail(config_error)

            cmd = [sys.executable, "-m", "llm_router_api.rest_api"]
            if args.host is not None:
                cmd += ["--host", args.host]
            if args.port is not None:
                cmd += ["--port", str(args.port)]

            if not args.no_port_check:
                port_error = cls._check_start_port(args, instance)
                if port_error is not None:
                    return cls.fail(port_error)

            if args.save_config:
                cls._save_config(args, instance)

            if args.foreground:
                return cls._run_foreground(
                    args,
                    instance,
                    pid_file,
                    cmd,
                    log_file_for(args, instance, shell_log_filename),
                )

            return cls._run_daemon(
                args,
                instance,
                pid_file,
                cmd,
                log_file_for(args, instance, shell_log_filename),
                lock=lock,
            )
        finally:
            release_start_lock(lock)

    @classmethod
    def _run_foreground(
        cls,
        args: argparse.Namespace,
        instance: InstancePaths,
        pid_file: Path,
        cmd: List[str],
        log_file: Path,
    ) -> int:
        """Run the server as a child of the CLI until it exits."""
        # Keep the PID file and run record in sync in foreground mode too,
        # so ``server status`` / ``server stop`` work exactly like for a
        # daemonized server.
        write_run_file(
            run_file_for(pid_file),
            cls.build_run_record(pid_file, log_file, cmd, args),
        )
        # Long-lived foreground process: its lifetime is owned by the
        # surrounding try/finally (PID + run-record cleanup), so a context
        # manager (which would wait) is wrong here.
        # pylint: disable-next=consider-using-with
        proc = subprocess.Popen(cmd)
        write_pid_file(pid_file, proc.pid)
        print(
            f"Running in foreground (pid={proc.pid}).\n"
            f"  stop: {cls._hint('stop', instance)}  (or Ctrl-C)",
            flush=True,
        )
        try:
            return proc.wait()
        finally:
            remove_pid_file(pid_file)
            try:
                run_file_for(pid_file).unlink()
            except OSError:
                pass

    @classmethod
    def _log_tail(cls, log_file: Path, n: int = 15) -> str:
        """
        Return the last *n* lines of *log_file*, indented for a CLI error.

        A daemon that dies during import leaves its traceback only in the
        daemon log, which nobody looks at from a shell. Echoing the tail turns
        "started successfully" into an actionable message. A missing or
        unreadable log is not worth a second error, so it yields an empty
        string and the caller keeps its own message.
        """
        try:
            with open(log_file, "rt", encoding="utf-8", errors="replace") as fh:
                lines = tail_lines(fh, n)
        except OSError:
            return ""
        if not lines:
            return ""
        formatted = []
        for line in lines:
            if not line.endswith("\n"):
                line += "\n"
            formatted.append(f"  {line}")
        return "\n  last log lines:\n" + "".join(formatted)

    @classmethod
    def _run_daemon(
        cls,
        args: argparse.Namespace,
        instance: InstancePaths,
        pid_file: Path,
        cmd: List[str],
        log_file: Path,
        *,
        lock: Optional[Path] = None,
    ) -> int:
        """Spawn the classic double-fork daemon and report its PID."""
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # Record the launch parameters next to the PID file so
        # ``server status`` can show them later.
        write_run_file(
            run_file_for(pid_file),
            cls.build_run_record(pid_file, log_file, cmd, args),
        )

        # Daemon mode: classic double-fork. The parent (CLI) waits for the
        # daemon to publish its PID and reports it; the daemon then execs
        # the server, so the PID file keeps pointing at the Gunicorn master.
        if os.fork() > 0:
            release_start_lock(lock)
            pid = _wait_for_pid(pid_file)
            if pid is None:
                return cls.fail(
                    f"the daemon did not start. Check the log file: "
                    f"{log_file}{cls._log_tail(log_file)}"
                )
            if _wait_gone(pid, _DAEMON_START_GRACE):
                remove_pid_file(pid_file)
                try:
                    run_file_for(pid_file).unlink()
                except OSError:
                    pass
                return cls.fail(
                    f"the server exited immediately after starting "
                    f"(pid={pid}).\n  log: {log_file}{cls._log_tail(log_file)}"
                )
            print(
                f"Server started (pid={pid}).\n"
                f"  log:    {log_file}\n"
                f"  pid:    {pid_file}\n"
                f"  stop:   {cls._hint('stop', instance)}\n"
                f"  reload: {cls._hint('reload', instance)}"
            )
            return 0

        # Child: it must not touch the start lock owned by the CLI process.
        lock = None

        os.setsid()
        if os.fork() > 0:
            os._exit(0)

        # Grandchild: the new daemon process.
        _redirect_stdio(log_file)
        write_pid_file(pid_file, os.getpid())
        os.execvpe(sys.executable, cmd, os.environ)
        return 127  # pragma: no cover - execvpe never returns

    @classmethod
    def _stop_instance(cls, pid_file: Path, force: bool) -> int:
        """Stop the single server recorded in *pid_file*."""
        pid = get_alive_pid(pid_file)
        if pid is None:
            print(
                f"No running server found (pid file: {pid_file}).",
                file=sys.stderr,
            )
            return 1

        try:
            if force:
                os.kill(pid, signal.SIGKILL)
                _wait_gone(pid, _KILL_POLL_SECONDS)
            else:
                os.kill(pid, signal.SIGTERM)
                if not _wait_gone(pid, _STOP_GRACE_SECONDS):
                    print(
                        f"Server (pid={pid}) did not exit within "
                        f"{_STOP_GRACE_SECONDS}s; retry with --force to SIGKILL.",
                        file=sys.stderr,
                    )
                    return 1
        except ProcessLookupError:
            pass

        remove_pid_file(pid_file)
        try:
            run_file_for(pid_file).unlink()
        except OSError:
            pass
        print(f"Server stopped (pid={pid}).")
        return 0

    @classmethod
    def _stop_all(cls, args: argparse.Namespace) -> int:
        """Stop every discovered instance (one that has state on disk)."""
        instances = discover_instances()
        if not instances:
            print("No running server found (no instances).", file=sys.stderr)
            return 1

        code = 0
        for instance in reversed(instances):
            pid = get_alive_pid(instance.pid_file)
            if pid is None:
                print(f"not running: {instance.name}")
                continue
            print(f"stopping {instance.name} (pid={pid}) ...", flush=True)
            if cls._stop_instance(instance.pid_file, args.force) != 0:
                print(f"  failed: {instance.name}", file=sys.stderr)
                code = 1
        return code

    @classmethod
    def _stop(cls, args: argparse.Namespace) -> int:
        """Stop one instance, or every known one with ``--all``."""
        conflict = cls._all_conflict(args)
        if conflict:
            return cls.fail(conflict)
        if getattr(args, "all", False):
            return cls._stop_all(args)

        instance, error = cls._instance(args)
        if error:
            return cls.fail(error)
        assert instance is not None
        return cls._stop_instance(cls._pid_file_for(args, instance), args.force)

    @classmethod
    def _restart_tokens(cls, record: Dict[str, Any]) -> List[str]:
        """
        Rebuild the ``start`` flags of a previous launch from its run record.

        Only the flags the original command line carried (``env_overrides``)
        are replayed: ``start`` applies the built-in defaults, the shell
        environment and the instance ``config.env`` again on its own, so an
        edit made to ``config.env`` still takes effect on a reload.
        ``--models-config`` comes from the record's absolute path, which keeps
        pointing at the file the running server actually loaded even when the
        reload is issued from a different directory.
        """
        overrides = record.get("env_overrides")
        if not isinstance(overrides, dict):
            overrides = {}

        tokens: List[str] = []
        for env_key, value in overrides.items():
            entry = cls._RELOAD_FLAGS.get(str(env_key))
            if entry is None or env_key == "LLM_ROUTER_MODELS_CONFIG":
                continue
            flag, attr, convert = entry
            token = cls._flag_token(attr, convert, value)
            if token is None:
                continue
            tokens.append(flag)
            if token:
                tokens.append(token)

        models_config = record.get("models_config") or overrides.get(
            "LLM_ROUTER_MODELS_CONFIG"
        )
        if models_config:
            tokens += ["--models-config", str(models_config)]
        return tokens

    @classmethod
    def _flag_token(
        cls, attr: str, convert: Optional[str], value: Any
    ) -> Optional[str]:
        """
        Render a recorded environment *value* as the token of its ``start`` flag.

        ``None`` drops the flag, ``""`` stands for a valueless one
        (``--verbose``). Every value is checked against what the flag itself
        accepts, so a stale or hand-edited run record degrades into "flag
        omitted" instead of an argparse error after the server is already down.
        """
        text = str(value).strip()
        lowered = text.lower()
        if attr == "verbose":
            return "" if lowered in _TRUE_TOKENS else None
        if attr == "server":
            return text if text in cls._SERVER_TYPES else None
        if attr == "lb_strategy":
            return text if text in cls._LB_STRATEGIES else None
        if convert == "bool":
            if lowered in _TRUE_TOKENS:
                return "1"
            return "0" if lowered in _FALSE_TOKENS else None
        if not text:
            return None
        if attr in cls._NUMERIC_FLAGS and not text.isdigit():
            return None
        if attr in cls._BOOL_FLAGS and text not in ("0", "1"):
            return None
        return text

    @classmethod
    def _restart_argv(
        cls,
        instance: InstancePaths,
        pid_file: Path,
        record: Dict[str, Any],
    ) -> List[str]:
        """Build the complete ``server start`` command line that restarts *record*."""
        argv = [cls.START_NAME, *cls._restart_tokens(record)]
        if pid_file != instance.pid_file:
            # The instance was addressed through an explicit --pid-file, which
            # the restart has to honor or it would start a second server.
            argv += ["--pid-file", str(pid_file)]
        if record.get("log_file"):
            argv += ["--log-file", str(record["log_file"])]
        return argv

    @classmethod
    def _restart(
        cls,
        instance: InstancePaths,
        pid_file: Path,
        record: Dict[str, Any],
    ) -> int:
        """
        Start the server again with the settings *record* was launched with.

        The namespace comes from the real ``start`` parser, so a restart can
        never drift from what ``server start`` itself accepts.
        """
        argv = cls._restart_argv(instance, pid_file, record)
        try:
            start_args = cls.build_parser().parse_args(argv)
        except SystemExit:  # pragma: no cover - defensive, tokens are validated
            return cls.fail(
                "reload could not rebuild the start command from "
                f"{run_file_for(pid_file)}; start the server yourself:\n"
                f"  llm-router {' '.join(argv)}"
            )
        code = cls._start(start_args)
        if code != 0:
            print(
                f"Reload incomplete: {instance.name} is stopped. Fix the "
                f"problem and start it again: {cls._hint('start', instance)}",
                file=sys.stderr,
            )
        return code

    @classmethod
    def _reload_graceful(cls, pid: int) -> int:
        """Send SIGHUP to the running master (Gunicorn recycles its workers)."""
        try:
            os.kill(pid, signal.SIGHUP)
        except ProcessLookupError:
            return cls.fail(f"the server (pid={pid}) exited before the signal")
        print(
            f"Graceful reload requested: SIGHUP sent to pid={pid}; "
            "Gunicorn is recycling workers."
        )
        return 0

    @classmethod
    def _reload(cls, args: argparse.Namespace) -> int:
        """
        Reload the server: stop the running one, then start it again.

        A restart is the only reload that picks up what Gunicorn cannot:
        another models config, another port or engine, or code changes. The
        flags of the previous launch are replayed from the run record, so the
        server comes back the way it went down. ``--force`` skips the SIGTERM
        grace period, ``--graceful`` keeps the old SIGHUP-only behavior.
        """
        instance, error = cls._instance(args)
        if error:
            return cls.fail(error)
        assert instance is not None
        pid_file = cls._pid_file_for(args, instance)
        pid = get_alive_pid(pid_file)
        if pid is None:
            print(
                f"No running server found (pid file: {pid_file}).\n"
                f"Start one: {cls._hint('start', instance)}",
                file=sys.stderr,
            )
            return 1

        if getattr(args, "graceful", False):
            return cls._reload_graceful(pid)

        # The run record goes away with the PID file, so the launch settings
        # have to be read while the server is still up.
        record = read_run_file(run_file_for(pid_file)) or {}

        # Restarting with a models config that cannot be loaded would take a
        # working instance down for nothing (and a failed start removes a named
        # instance's state directory), so check the recorded path first.
        recorded_config = str(record.get("models_config") or "")
        if recorded_config:
            problem = cls._models_config_problem(recorded_config)
            if problem:
                return cls.fail(
                    f"reload aborted: the models config {problem}: "
                    f"{recorded_config}{cls._scope(instance)}. The server is "
                    "left running — fix the configuration and reload again."
                )

        print(f"Reloading: stopping the server (pid={pid}) ...", flush=True)
        if cls._stop_instance(pid_file, bool(getattr(args, "force", False))) != 0:
            return cls.fail(
                "reload aborted: the server is still running"
                f"{cls._scope(instance)}. Stop it with "
                f"'{cls._hint('stop', instance)} --force', then start it "
                f"with '{cls._hint('start', instance)}'"
            )

        print(
            f"Reloading: starting the server again{cls._scope(instance)} ...",
            flush=True,
        )
        return cls._restart(instance, pid_file, record)

    @classmethod
    def _status_all(cls, color: bool) -> int:
        """Print a compact one-line-per-instance summary."""
        instances = discover_instances()
        if not instances:
            print("No instances found.")
            return 1

        rows: List[Tuple[str, str, str]] = []
        running = 0
        for instance in instances:
            pid = get_alive_pid(instance.pid_file)
            if pid is None:
                status = _paint(color, "31", "● stopped")
                detail = str(instance.pid_file)
            else:
                running += 1
                status = _paint(color, "32", "● running")
                detail = cls._running_line(
                    pid, read_run_file(instance.run_file) or {}
                )
            rows.append((instance.name, status, detail))

        width = max(len(name) for name, _, _ in rows)
        lines = [
            "  " + _paint(color, "1;90", f"Instances ({len(instances)})"),
            "",
        ]
        lines += [
            f"  {name:<{width}}  {status}  {detail}" for name, status, detail in rows
        ]
        print("\n".join(lines))
        return 0 if running == len(instances) else 1

    @classmethod
    def _status(cls, args: argparse.Namespace) -> int:
        """Report whether the server is running, with its launch parameters."""
        conflict = cls._all_conflict(args)
        if conflict:
            return cls.fail(conflict)
        color = _resolve_color(getattr(args, "color", "auto"))
        if getattr(args, "all", False):
            return cls._status_all(color)

        instance, error = cls._instance(args)
        if error:
            return cls.fail(error)
        assert instance is not None
        show_env = bool(getattr(args, "show_env", False))
        pid_file = cls._pid_file_for(args, instance)
        pid = get_alive_pid(pid_file)
        if pid is None:
            print(cls._render_status_down(color, pid_file))
            return 1

        record = read_run_file(run_file_for(pid_file)) or {}
        print(cls._render_status_up(color, pid, pid_file, record, show_env))
        return 0

    # ---- Status rendering ------------------------------------------------ #
    @classmethod
    def _running_line(cls, pid: int, record: Dict[str, Any]) -> str:
        """Build the one-line "Server is running (...)" summary."""
        pieces = [f"pid {pid}"]
        server = record.get("server")
        if server:
            pieces.append(str(server))
        env = cls._env_from_record(record)
        host = env.get("LLM_ROUTER_SERVER_HOST")
        port = env.get("LLM_ROUTER_SERVER_PORT")
        if host and host not in ("0.0.0.0", "127.0.0.1"):
            pieces.append(f"host {host}" + (f":{port}" if port else ""))
        elif port:
            pieces.append(f"port {port}")
        return "Server is running (" + ", ".join(pieces) + ")"

    @classmethod
    def _env_from_record(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        """Best-effort env mapping from *record* (``env`` else ``env_overrides``)."""
        env = record.get("env")
        if env is None:
            env = record.get("env_overrides")
        return dict(env) if isinstance(env, dict) else {}

    @classmethod
    def _detail_rows(
        cls, pid: int, pid_file: Path, record: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """Key/value rows for the Details section (in display order)."""
        env = cls._env_from_record(record)
        rows: List[Tuple[str, str]] = [
            ("PID", str(pid)),
        ]
        instance_name = record.get("instance")
        if instance_name not in (None, DEFAULT_INSTANCE):
            rows.append(("Instance", str(instance_name)))
        rows.append(
            (
                "Log",
                str(
                    record.get("app_log_file")
                    or env.get("LLM_ROUTER_LOG_FILENAME")
                    or DEFAULT_LOG_FILENAME
                ),
            )
        )
        rows.append(("PID file", str(pid_file)))
        if record.get("started_at"):
            rows.append(("Started", str(record["started_at"])))
        if record.get("server"):
            rows.append(("Server", str(record["server"])))
        if env.get("LLM_ROUTER_SERVER_HOST"):
            rows.append(("Host", str(env["LLM_ROUTER_SERVER_HOST"])))
        if env.get("LLM_ROUTER_SERVER_PORT"):
            rows.append(("Port", str(env["LLM_ROUTER_SERVER_PORT"])))
        if record.get("models_config") or env.get("LLM_ROUTER_MODELS_CONFIG"):
            rows.append(
                (
                    "Models config",
                    str(
                        record.get("models_config")
                        or env.get("LLM_ROUTER_MODELS_CONFIG")
                    ),
                )
            )
        if record.get("command"):
            rows.append(
                ("Command", " ".join(str(part) for part in record["command"]))
            )
        return rows

    @classmethod
    def _kv_block(
        cls,
        color: bool,
        title: str,
        rows: List[Tuple[str, str]],
    ) -> List[str]:
        """Render a two-column *rows* block (label padded to the widest key)."""
        lines = ["  " + _paint(color, "1;90", title)]
        if not rows:
            return lines
        width = max(len(key) for key, _ in rows)
        for key, value in rows:
            lines.append(
                "    " + _paint(color, "90", f"{key:<{width}}") + "  " + value
            )
        return lines

    @classmethod
    def _render_status_up(
        cls,
        color: bool,
        pid: int,
        pid_file: Path,
        record: Dict[str, Any],
        show_env: bool,
    ) -> str:
        """Render the "running" card."""
        lines = [
            "  " + _paint(color, "1;32", "✓ All good"),
            "  " + _paint(color, "32", "●") + "  " + cls._running_line(pid, record),
            "",
        ]
        lines.extend(
            cls._kv_block(color, "Details", cls._detail_rows(pid, pid_file, record))
        )

        if show_env:
            env = cls._env_from_record(record)
            if env:
                env_rows = [
                    (key, _MASKED if _is_sensitive(key) else str(env[key]))
                    for key in sorted(env)
                ]
                lines.append("")
                lines.extend(
                    cls._kv_block(color, f"Environment ({len(env_rows)})", env_rows)
                )
            else:
                lines.append("")
                lines.append(
                    "  " + _paint(color, "90", "Environment (none recorded)")
                )
        return "\n".join(lines)

    @classmethod
    def _render_status_down(cls, color: bool, pid_file: Path) -> str:
        """Render the "not running" card."""
        lines = [
            "  " + _paint(color, "1;31", "✗ Not running"),
            "  "
            + _paint(color, "31", "●")
            + "  Server is not running (no live process for this PID file).",
            "",
        ]
        lines.extend(cls._kv_block(color, "Details", [("PID file", str(pid_file))]))
        return "\n".join(lines)

    # ---- Instance listing / removal -------------------------------------- #
    @classmethod
    def _list_entry(cls, instance: InstancePaths) -> Dict[str, Any]:
        """Collect the ``list`` row of *instance* (run record + live PID)."""
        pid = get_alive_pid(instance.pid_file)
        record = read_run_file(instance.run_file) or {}
        env = cls._env_from_record(record)
        return {
            "name": instance.name,
            "status": "running" if pid is not None else "stopped",
            "pid": pid,
            "port": env.get("LLM_ROUTER_SERVER_PORT"),
            "server": record.get("server") or env.get("LLM_ROUTER_SERVER_TYPE"),
            "started_at": record.get("started_at"),
            "pid_file": str(instance.pid_file),
            "log_file": record.get("log_file") or str(instance.daemon_log),
            "app_log_file": record.get("app_log_file")
            or (str(instance.app_log) if instance.named else ""),
            "models_config": record.get("models_config")
            or env.get("LLM_ROUTER_MODELS_CONFIG"),
        }

    @classmethod
    def _list(cls, args: argparse.Namespace) -> int:
        """Print every known instance (``--json`` for scripting)."""
        entries = [cls._list_entry(item) for item in discover_instances()]
        if getattr(args, "json", False):
            print(json.dumps(entries, indent=2))
            return 0

        if not entries:
            print("no instances found")
            return 0

        color = _resolve_color(getattr(args, "color", "auto"))
        headers = ("NAME", "STATUS", "PID", "PORT", "SERVER", "STARTED", "LOG")
        rows = [
            [
                entry["name"],
                f"● {entry['status']}",
                "-" if entry["pid"] is None else str(entry["pid"]),
                "-" if entry["port"] is None else str(entry["port"]),
                entry["server"] or "-",
                entry["started_at"] or "-",
                entry["app_log_file"] or entry["log_file"] or "-",
            ]
            for entry in entries
        ]
        widths = [
            max([len(header)] + [len(row[column]) for row in rows])
            for column, header in enumerate(headers)
        ]
        lines = [
            _paint(
                color,
                "1;90",
                "  ".join(
                    header.ljust(widths[column])
                    for column, header in enumerate(headers)
                ).rstrip(),
            )
        ]
        for row in rows:
            cells = []
            for column, cell in enumerate(row):
                if column == len(row) - 1:
                    cells.append(cell)
                    continue
                padded = cell.ljust(widths[column])
                if column == 1:
                    padded = _paint(
                        color,
                        "32" if cell.endswith("running") else "31",
                        padded.rstrip(),
                    )
                cells.append(padded)
            lines.append("  ".join(cells).rstrip())
        print("\n".join(lines))
        return 0

    @classmethod
    def _rm_instance(
        cls, args: argparse.Namespace, instance: Optional[InstancePaths] = None
    ) -> int:
        """Delete a named instance's state directory (must not be running)."""
        try:
            instance = instance or resolve_instance(
                argparse.Namespace(instance=args.name)
            )
        except ValueError as exc:
            return cls.fail(str(exc))

        if instance.name == DEFAULT_INSTANCE:
            return cls.fail(
                f"{DEFAULT_INSTANCE} is the built-in instance and cannot "
                "be removed"
            )

        pid = get_alive_pid(instance.pid_file)
        if pid is not None:
            return cls.fail(
                f"instance '{instance.name}' is running (pid={pid}). "
                f"Stop it first: {cls._hint('stop', instance)}"
            )
        if not instance.dir.is_dir():
            return cls.fail(f"no such instance: {instance.name}")

        shutil.rmtree(instance.dir)
        print(f"Removed instance '{instance.name}' ({instance.dir})")
        return 0

    # ---- Log following --------------------------------------------------- #
    @classmethod
    def _resolve_log_file(
        cls, args: argparse.Namespace, instance: InstancePaths
    ) -> Path:
        """Resolve the log file for ``server log``.

        Explicit ``--log-file`` wins. Otherwise the application's own log:
        ``app_log_file`` from the run record (written at start, even in
        ``--foreground`` mode), else the shell's ``LLM_ROUTER_LOG_FILENAME``
        (anchored to the instance directory for a named instance, to the CWD
        for the legacy ``default`` one), else the instance's own log file.
        """
        if args.log_file:
            return Path(args.log_file).expanduser()
        pid_file = cls._pid_file_for(args, instance)
        record = read_run_file(run_file_for(pid_file)) or {}
        app_log = record.get("app_log_file")
        if app_log:
            return Path(app_log).expanduser()
        name = os.environ.get("LLM_ROUTER_LOG_FILENAME")
        if instance.named and instance.app_log is not None:
            return Path(resolve_instance_app_log(instance, name, create=False))
        if name:
            return Path(anchor_log_name(name))
        return Path(anchor_log_name(DEFAULT_LOG_FILENAME))

    @classmethod
    def _log(cls, args: argparse.Namespace) -> int:
        """Tail (and by default follow) the server log with colored levels."""
        instance, error = cls._instance(args)
        if error:
            return cls.fail(error)
        assert instance is not None
        log_file = cls._resolve_log_file(args, instance)
        if not log_file.exists():
            print(
                f"Log file not found: {log_file}\n"
                f"Start the server first: {cls._hint('start', instance)}\n"
                "To follow the daemon's console log explicitly:\n"
                f"  llm-router server log --log-file {instance.daemon_log}",
                file=sys.stderr,
            )
            return 1

        color = args.color
        if color == "auto":
            color = "always" if sys.stdout.isatty() else "never"

        with open(log_file, "r", encoding="utf-8", errors="replace") as fh:
            for line in tail_lines(fh, args.lines):
                print(colorize_line(line.rstrip("\n"), color))

            if args.no_follow:
                return 0

            try:
                while True:
                    chunk = fh.readline()
                    if chunk:
                        print(colorize_line(chunk.rstrip("\n"), color), flush=True)
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                return 0
