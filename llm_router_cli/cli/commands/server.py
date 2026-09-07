"""
Server lifecycle subcommands for ``llm-router``.

Wraps the REST API entry point (``python -m llm_router_api.rest_api``) in a
managed background daemon with a PID file, so the same lifecycle operations
``run-rest-api-gunicorn.sh`` performs can be driven from the CLI::

    llm-router server start    # start in the background (daemon, PID file)
    llm-router server status   # show whether the server is running
    llm-router server log      # follow the log (tail -f style, colored levels)
    llm-router server stop    # SIGTERM (with grace period), or SIGKILL --force
    llm-router server reload  # graceful SIGHUP to the Gunicorn master

Unless the user's environment already defines them, the command applies the
same ``LLM_ROUTER_*`` defaults as ``run-rest-api-gunicorn.sh``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time

from collections import deque
from pathlib import Path
from typing import Any, ClassVar, Dict, IO, List, Optional, Tuple

from llm_router_cli.cli.commands.base import BaseCommand

#: Per-user state directory (same home location as ``memory-keys.json``).
_STATE_DIR = Path.home() / ".llm-router"
DEFAULT_PID_FILE = _STATE_DIR / "server.pid"
DEFAULT_LOG_FILE = _STATE_DIR / "server.log"

#: How long to wait for SIGTERM before telling the user to use ``--force``.
_STOP_GRACE_SECONDS = 15
_STOP_POLL_INTERVAL = 0.2
_KILL_POLL_SECONDS = 5

#: ``LLM_ROUTER_*`` defaults mirrored from ``run-rest-api-gunicorn.sh``.
#: Applied with :func:`os.environ.setdefault`, so the user's shell always wins.
DEFAULT_ENV: Dict[str, str] = {
    # Logging
    "LLM_ROUTER_IN_DEBUG": "1",
    "LLM_ROUTER_MINIMUM": "1",
    "LLM_ROUTER_LOG_FILENAME": "llm-router.log",
    "LLM_ROUTER_LOG_TO_FILE": "1",
    "LLM_ROUTER_LOG_LEVEL": "INFO",
    "LLM_ROUTER_LOG_MAX_BYTES": "52428800",
    "LLM_ROUTER_LOG_BACKUP_COUNT": "5",
    # Metrics
    "LLM_ROUTER_USE_PROMETHEUS": "1",
    # Router resources
    "LLM_ROUTER_PROMPTS_DIR": "resources/prompts",
    "LLM_ROUTER_MODELS_CONFIG": "resources/configs/models-config.json",
    # Request limits
    "LLM_ROUTER_MAX_REQUEST_BODY_SIZE": "10485760",
    # Endpoints / routing
    "LLM_ROUTER_EP_PREFIX": "/api",
    "LLM_ROUTER_DEFAULT_EP_LANGUAGE": "pl",
    "LLM_ROUTER_BALANCE_STRATEGY": "balanced",
    # Server engine
    "LLM_ROUTER_SERVER_TYPE": "gunicorn",
    "LLM_ROUTER_SERVER_PORT": "8080",
    "LLM_ROUTER_SERVER_HOST": "0.0.0.0",
    "LLM_ROUTER_SERVER_WORKERS_COUNT": "4",
    "LLM_ROUTER_SERVER_THREADS_COUNT": "16",
    "LLM_ROUTER_SERVER_WORKER_CLASS": "",
    "LLM_ROUTER_TIMEOUT": "0",
    "LLM_ROUTER_EXTERNAL_TIMEOUT": "300",
    # Redis
    "LLM_ROUTER_REDIS_HOST": "",
    "LLM_ROUTER_REDIS_PORT": "6379",
    "LLM_ROUTER_REDIS_DB": "0",
    "LLM_ROUTER_REDIS_PASSWORD": "",
    "LLM_ROUTER_REDIS_PROTOCOL": "3",
    # Monitoring
    "LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS": "5",
    "LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS": "1",
    "LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS": "5",
    "LLM_ROUTER_PROVIDER_MONITOR_PING_TIMEOUT_SECONDS": "5.0",
    "LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES": "2",
    # Masking
    "LLM_ROUTER_FORCE_MASKING": "0",
    "LLM_ROUTER_MASKING_WITH_AUDIT": "0",
    "LLM_ROUTER_MASKING_STRATEGY_PIPELINE": "fast_masker",
    # Guardrails
    "LLM_ROUTER_FORCE_GUARDRAIL_REQUEST": "0",
    "LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST": "0",
    "LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST": "",
    "LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST": "",
    "LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST": "",
    "LLM_ROUTER_MASKER_PII_HOST": "",
    # Authentication
    "LLM_ROUTER_AUTH_ENABLED": "false",
    "LLM_ROUTER_AUTH_KEY_STORE": "memory",
    "LLM_ROUTER_AUTH_MEMORY_SEED_FILE": "~/.llm-router/configs/auth/memory-keys.json",
    "LLM_ROUTER_AUTH_REDIS_HOST": "",
    "LLM_ROUTER_AUTH_REDIS_PORT": "6379",
    "LLM_ROUTER_AUTH_REDIS_DB": "0",
    "LLM_ROUTER_AUTH_REDIS_PASSWORD": "",
    "LLM_ROUTER_AUTH_REDIS_PROTOCOL": "3",
    "LLM_ROUTER_AUTH_VAULT_ADDR": "",
    "LLM_ROUTER_AUTH_VAULT_PATH": "secret/data/llm-router/api-keys",
    "LLM_ROUTER_AUTH_VAULT_AUTH_METHOD": "kubernetes",
    "LLM_ROUTER_AUTH_VAULT_ROLE_ID": "",
    "LLM_ROUTER_AUTH_VAULT_SECRET_ID": "",
    "LLM_ROUTER_AUTH_KEY_CACHE_TTL": "300",
    "LLM_ROUTER_AUTH_KEY_CACHE_JITTER": "60",
    "LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT": "60",
    "LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS": "/metrics,/health",
    "LLM_ROUTER_TRUSTED_PROXIES": "",
    "LLM_ROUTER_AUTH_FAILURE_LIMIT": "20",
    "LLM_ROUTER_AUTH_KEY_PREFIX": "sk-llmr-live",
    "LLM_ROUTER_AUTH_KEY_LENGTH": "48",
    "LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD": "3600",
    "LLM_ROUTER_AUTH_AUDIT": "",
    # Plugins / utils
    "LLM_ROUTER_UTILS_PLUGINS_PIPELINE": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CONFIG": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_MODEL": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_TARGETS": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_SIZE": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_OVERLAP": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_PERSIST_DIR": "",
    "LLM_ROUTER_LANGCHAIN_RAG_COLLECTION": "",
    "LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER": "",
    "LLM_ROUTER_LANGCHAIN_RAG_DEVICE": "cpu",
    "LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE": "1024",
    "LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP": "100",
    "LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR": "",
    "TOKENIZERS_PARALLELISM": "true",
}


# -------------------------------------------------------------------------- #
# Environment defaults
# -------------------------------------------------------------------------- #
def apply_default_env() -> None:
    """Apply :data:`DEFAULT_ENV` without overriding variables already set."""
    for key, value in DEFAULT_ENV.items():
        os.environ.setdefault(key, value)


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
    return deque(fh, maxlen=n)


# -------------------------------------------------------------------------- #
# Command
# -------------------------------------------------------------------------- #
class ServerCommand(BaseCommand):
    """Manage the LLM-Router REST API server (start / stop / reload / status / log)."""

    NAME: ClassVar[str] = "server"
    HELP: ClassVar[str] = (
        "Manage the LLM-Router REST API server (start/stop/reload/status/log)"
    )
    SUBPARSER_DEST: ClassVar[str] = "server_command"

    START_NAME = "start"
    STOP_NAME = "stop"
    RELOAD_NAME = "reload"
    STATUS_NAME = "status"
    LOG_NAME = "log"
    START_HELP = "Start the REST API server in the background (daemon)"
    STOP_HELP = "Stop the running REST API server"
    RELOAD_HELP = "Gracefully reload the running Gunicorn master (SIGHUP)"
    STATUS_HELP = "Show server status (pid, log, launch parameters)"
    LOG_HELP = "Follow the server log (tail -f style, colorized levels)"

    #: (namespace attribute, environment variable, value converter) pairs
    #: applied when the corresponding flag is given to ``server start``.
    _ENV_OVERRIDES: ClassVar[List[Tuple[str, str, Optional[str]]]] = [
        ("models_config", "LLM_ROUTER_MODELS_CONFIG", None),
        ("debug", "LLM_ROUTER_IN_DEBUG", "str"),
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
    ]

    _LB_STRATEGIES = [
        "balanced",
        "weighted",
        "first_available",
        "first_available_optim",
    ]

    # ---- Registration ---------------------------------------------------- #
    @classmethod
    def _add_pid_file_arg(cls, p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--pid-file",
            default=str(DEFAULT_PID_FILE),
            help="PID file location (default: %(default)s)",
        )

    @classmethod
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the *start* / *stop* / *reload* / *status* sub-commands."""
        start = subparsers.add_parser(cls.START_NAME, help=cls.START_HELP)
        start.add_argument(
            "--foreground",
            action="store_true",
            help="Run in the foreground instead of daemonizing (for debugging).",
        )
        start.add_argument(
            "--log-file",
            default=str(DEFAULT_LOG_FILE),
            help="Server log file used in daemon mode (default: %(default)s)",
        )
        start.add_argument(
            "--server",
            choices=["gunicorn", "waitress", "flask"],
            default=None,
            help="WSGI server engine (default: LLM_ROUTER_SERVER_TYPE or gunicorn)",
        )
        start.add_argument("--host", default=None, help="Interface to bind to")
        start.add_argument("--port", type=int, default=None, help="Port number")
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
            "--lb-strategy",
            choices=cls._LB_STRATEGIES,
            default=None,
            help="Routing/balance strategy (LLM_ROUTER_BALANCE_STRATEGY)",
        )
        start.add_argument(
            "--default-lang",
            default=None,
            help="Default endpoint language, e.g. 'pl' (LLM_ROUTER_DEFAULT_EP_LANGUAGE)",
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

        stop = subparsers.add_parser(cls.STOP_NAME, help=cls.STOP_HELP)
        stop.add_argument(
            "--force",
            action="store_true",
            help="Skip the SIGTERM grace period and send SIGKILL instead.",
        )
        cls._add_pid_file_arg(stop)

        reload = subparsers.add_parser(cls.RELOAD_NAME, help=cls.RELOAD_HELP)
        cls._add_pid_file_arg(reload)

        status = subparsers.add_parser(cls.STATUS_NAME, help=cls.STATUS_HELP)
        cls._add_pid_file_arg(status)

        log = subparsers.add_parser(cls.LOG_NAME, help=cls.LOG_HELP)
        log.add_argument(
            "--log-file",
            default=str(DEFAULT_LOG_FILE),
            help="Server log file to follow (default: %(default)s)",
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
        log.add_argument(
            "--color",
            choices=["auto", "always", "never"],
            default="auto",
            help="Colorize log levels (auto = only on a TTY, default: %(default)s)",
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
    ) -> Dict[str, Any]:
        """Build the JSON record describing how the server was started."""
        return {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "executable": sys.executable,
            "command": cmd,
            "server": os.environ.get("LLM_ROUTER_SERVER_TYPE", "gunicorn"),
            "log_file": str(log_file),
            "pid_file": str(pid_file),
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
        cls.build_parser().print_help()
        return 0

    # ---- Actions --------------------------------------------------------- #
    @classmethod
    def _start(cls, args: argparse.Namespace) -> int:
        """Start the API server (daemonized by default)."""
        pid_file = Path(args.pid_file).expanduser()
        alive = get_alive_pid(pid_file)
        if alive is not None:
            print(
                f"Error: a server is already running (pid={alive}, "
                f"pid file: {pid_file}).\n"
                "Use 'llm-router server reload' or 'llm-router server stop'.",
                file=sys.stderr,
            )
            return 1

        apply_default_env()
        if args.server:
            os.environ.setdefault("LLM_ROUTER_SERVER_TYPE", args.server)
        # Explicit CLI flags win over both the defaults and the shell env.
        os.environ.update(cls.build_env_overrides(args))

        cmd = [sys.executable, "-m", "llm_router_api.rest_api"]
        if args.host is not None:
            cmd += ["--host", args.host]
        if args.port is not None:
            cmd += ["--port", str(args.port)]

        if args.foreground:
            return subprocess.call(cmd)

        log_file = Path(args.log_file).expanduser()
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
            pid = _wait_for_pid(pid_file)
            if pid is None:
                print(
                    "Error: the daemon did not start. Check the log file: "
                    f"{log_file}",
                    file=sys.stderr,
                )
                return 1
            print(
                f"Server started (pid={pid}).\n"
                f"  log:    {log_file}\n"
                f"  pid:    {pid_file}\n"
                f"  stop:   llm-router server stop\n"
                f"  reload: llm-router server reload"
            )
            return 0

        os.setsid()
        if os.fork() > 0:
            os._exit(0)

        # Grandchild: the new daemon process.
        _redirect_stdio(log_file)
        write_pid_file(pid_file, os.getpid())
        os.execvpe(sys.executable, cmd, os.environ)
        return 127  # pragma: no cover - execvpe never returns

    @classmethod
    def _stop(cls, args: argparse.Namespace) -> int:
        """Stop the server recorded in the PID file."""
        pid_file = Path(args.pid_file).expanduser()
        pid = get_alive_pid(pid_file)
        if pid is None:
            print(
                f"No running server found (pid file: {pid_file}).",
                file=sys.stderr,
            )
            return 1

        try:
            if args.force:
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
    def _reload(cls, args: argparse.Namespace) -> int:
        """Send SIGHUP to the server (Gunicorn master recycles workers)."""
        pid_file = Path(args.pid_file).expanduser()
        pid = get_alive_pid(pid_file)
        if pid is None:
            print(
                f"No running server found (pid file: {pid_file}).",
                file=sys.stderr,
            )
            return 1

        os.kill(pid, signal.SIGHUP)
        print(
            f"Graceful reload requested: SIGHUP sent to pid={pid}; "
            "Gunicorn is recycling workers."
        )
        return 0

    @classmethod
    def _status(cls, args: argparse.Namespace) -> int:
        """Report whether the server is running, with its launch parameters."""
        pid_file = Path(args.pid_file).expanduser()
        pid = get_alive_pid(pid_file)
        if pid is None:
            print(f"Server is NOT running (pid file: {pid_file}).")
            return 1

        record = read_run_file(run_file_for(pid_file)) or {}
        lines = [
            f"Server is running (pid={pid}).",
            f"  pid file: {pid_file}",
            f"  log:      {record.get('log_file', DEFAULT_LOG_FILE)}",
        ]
        if record.get("started_at"):
            lines.append(f"  started:  {record['started_at']}")
        if record.get("server"):
            lines.append(f"  server:   {record['server']}")
        if record.get("command"):
            lines.append(
                f"  command:  {' '.join(str(part) for part in record['command'])}"
            )
        overrides = record.get("env_overrides") or {}
        if overrides:
            lines.append("  overrides:")
            lines.extend(f"    {key}={value}" for key, value in overrides.items())
        elif record:
            lines.append("  overrides: (none — using shell env / script defaults)")
        print("\n".join(lines))
        return 0

    # ---- Log following --------------------------------------------------- #
    @classmethod
    def _log(cls, args: argparse.Namespace) -> int:
        """Tail (and by default follow) the server log with colored levels."""
        log_file = Path(args.log_file).expanduser()
        if not log_file.exists():
            print(
                f"Log file not found: {log_file}\n"
                "Start the server first: llm-router server start",
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
