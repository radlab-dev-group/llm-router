"""
CLI commands for API key management.

Usage::

    llm-router auth key generate [--policy developer] [--store memory]
    llm-router auth key list [--store memory] [--json]
    llm-router auth key delete <key-id> [--store memory]
    llm-router auth key disable <key-id> [--store memory]
    llm-router auth key enable <key-id> [--store memory]
    llm-router auth key rotate <key-id> [--grace 3600]
    llm-router auth policy list
    llm-router auth policy create <name> <json-policy>
    llm-router auth rate-limit list
    llm-router auth rate-limit apply <key-id> --preset <name> [--store memory]
    llm-router auth rate-limit remove <key-id> [--store memory]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from llm_router_cli.log_utils import setup_logging

from .base import BaseCommand

log = logging.getLogger(__name__)

__all__ = ["AuthCommand"]


class AuthCommand(BaseCommand):
    """
    Encapsulates the ``auth`` CLI subcommand and all its children.

    A single argparse tree is built once (see :meth:`register_children`) and
    dispatching happens **exclusively on the parsed namespace** — the raw
    argv is never re-scanned.
    """

    NAME = "auth"
    SUBPARSER_DEST = "auth_command"
    HELP = "Manage API keys and authentication"

    KEY_NAME = "key"
    POLICY_NAME = "policy"
    RATE_LIMIT_NAME = "rate-limit"
    STORE_BACKENDS = ("memory", "redis", "vault")
    KEY_COMMANDS = ("generate", "list", "delete", "disable", "enable", "rotate")
    KEY_MUTATE_ACTIONS = ("delete", "disable", "enable")

    SEED_DIR = Path.home() / ".llm-router"
    DEFAULT_SEED_FILE = str(SEED_DIR / "configs" / "auth" / "memory-keys.json")
    PRESET_FILE_NAME = "rate_limiting-policies.json"

    # ---- Built-in rate-limit presets (class-level constant) ---------------

    _BUILTIN_RATE_LIMIT_PRESETS: List[Dict[str, Any]] = [
        {"name": "free", "rpm": 10, "description": "Free tier — limited usage"},
        {"name": "basic", "rpm": 60, "description": "Standard (1/s)"},
        {"name": "pro", "rpm": 120, "description": "Pro tier (2/s)"},
        {"name": "enterprise", "rpm": 500, "description": "High throughput"},
    ]

    # ------------------------------------------------------------------ #
    # Error / table helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fail(message: str) -> int:
        """Print ``Error: message`` to stderr and return a failure exit code."""
        print(f"Error: {message}", file=sys.stderr)
        return 1

    @staticmethod
    def _render_table(
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        aligns: Optional[Sequence[str]] = None,
        min_widths: Optional[Sequence[int]] = None,
        gap: str = "  ",
    ) -> str:
        """Render *headers* and *rows* as an aligned plain-text table."""
        n_cols = len(headers)
        aligns = tuple(aligns or ("l" * n_cols))
        min_widths = min_widths or ()

        def width(col: int) -> int:
            widest = len(headers[col])
            for row in rows:
                widest = max(widest, len(str(row[col])))
            if col < len(min_widths):
                widest = max(widest, min_widths[col])
            return widest

        def format_row(cells: Sequence[str]) -> str:
            parts = []
            for i, cell in enumerate(cells):
                text = str(cell)
                if aligns[i] == "r":
                    parts.append(f"{text:>{width(i)}}")
                else:
                    parts.append(f"{text:<{width(i)}}")
            return gap.join(parts)

        separator = gap.join("-" * width(i) for i in range(n_cols))
        lines = [format_row(headers), separator, *(format_row(r) for r in rows)]
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Argument-adding helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def _add_store_and_redis_args(cls, p: argparse.ArgumentParser) -> None:
        """
        Add ``--store`` and all ``--auth-redis-*`` flags to *p*.
        """
        p.add_argument(
            "--store",
            default="memory",
            choices=AuthCommand.STORE_BACKENDS,
            help="Key store backend (default: memory)",
        )
        p.add_argument(
            "--auth-redis-host",
            default=None,
            help="Redis host for auth key store "
            "(default: env LLM_ROUTER_AUTH_REDIS_HOST)",
        )
        p.add_argument(
            "--auth-redis-port",
            type=int,
            default=None,
            help="Redis port for auth key store (default: env or 6379)",
        )
        p.add_argument(
            "--auth-redis-db",
            type=int,
            default=None,
            help="Redis database for auth key store (default: env or 0)",
        )
        p.add_argument(
            "--auth-redis-password",
            default=None,
            help="Redis password for auth key store (default: env)",
        )
        p.add_argument(
            "--auth-redis-protocol",
            type=int,
            choices=[2, 3],
            default=2,
            help="Redis protocol version for auth key store: "
            "2 (RESP2) or 3 (RESP3), default 2",
        )
        # Store-touching commands get --verbose (local-only commands don't).
        cls.add_verbose(p)

    @staticmethod
    def _add_key_id_arg(p: argparse.ArgumentParser) -> None:
        """
        Add the positional ``key_id`` argument to *p*.
        """
        p.add_argument("key_id", help="Key ID to operate on")

    # ------------------------------------------------------------------ #
    # Seed / store setup
    # ------------------------------------------------------------------ #
    @classmethod
    def _ensure_seed_env(cls) -> None:
        """
        Ensure the seed directory structure and the shipped presets exist.
        """
        cls.SEED_DIR.mkdir(parents=True, exist_ok=True)
        (cls.SEED_DIR / "configs" / "auth").mkdir(parents=True, exist_ok=True)
        cls._seed_policies(cls.SEED_DIR / "configs")

    @staticmethod
    def _cli_or_env(args: Any, attr: str, env_name: str, default: Any = None) -> Any:
        """
        Resolve a value from the CLI arg *attr*, falling back to the
        environment variable *env_name*, then to *default*.

        An explicit ``None`` CLI value falls through (the argparse default
        when the flag is omitted); any other value — including ``0`` — wins.
        """
        value = getattr(args, attr, None)
        if value is not None:
            return value
        env_value = os.environ.get(env_name)
        return default if env_value is None else env_value

    @classmethod
    def _auth_redis_kwargs(cls, args: Any) -> Dict[str, Any]:
        """
        Build redis kwargs for the auth key store (CLI args → env vars).
        """
        prefix = "LLM_ROUTER_AUTH_REDIS_"

        def _int(attr: str, env_suffix: str, default: int) -> int:
            return int(cls._cli_or_env(args, attr, prefix + env_suffix, default))

        return {
            "redis_host": cls._cli_or_env(args, "auth_redis_host", prefix + "HOST"),
            "redis_port": _int("auth_redis_port", "PORT", 6379),
            "redis_db": _int("auth_redis_db", "DB", 0),
            "redis_password": cls._cli_or_env(
                args, "auth_redis_password", prefix + "PASSWORD"
            ),
            "redis_protocol": _int("auth_redis_protocol", "PROTOCOL", 2),
        }

    @staticmethod
    def _vault_kwargs() -> Dict[str, Any]:
        """
        Build vault kwargs for the auth key store from the standard
        ``LLM_ROUTER_AUTH_VAULT_*`` environment variables (same source the
        server engine uses — see ``core/engine.py``).
        """

        def _get(name: str, default: str = "") -> str:
            return os.environ.get(name, default).strip()

        return {
            "addr": _get("LLM_ROUTER_AUTH_VAULT_ADDR"),
            "mount_path": _get("LLM_ROUTER_AUTH_VAULT_PATH")
            or "secret/data/llm-router/api-keys",
            "auth_method": (
                _get("LLM_ROUTER_AUTH_VAULT_AUTH_METHOD", "kubernetes").lower()
                or "kubernetes"
            ),
            "role_id": _get("LLM_ROUTER_AUTH_VAULT_ROLE_ID"),
            "secret_id": _get("LLM_ROUTER_AUTH_VAULT_SECRET_ID"),
        }

    def _make_store(self, args: Any) -> Any:
        """
        Create the key store selected by ``--store``, forwarding the
        right kwargs (redis or vault) to the shared factory.
        """
        from llm_router_api.core.auth.key_store import create_key_store

        log.debug("Key store backend: %s", args.store)
        if args.store == "vault":
            kwargs = self._vault_kwargs()
            if not kwargs["addr"]:
                raise ValueError(
                    "LLM_ROUTER_AUTH_VAULT_ADDR is required for "
                    "--store vault (vault address, e.g. http://127.0.0.1:8200)"
                )
            log.debug(
                "Vault: addr=%s mount=%s auth=%s",
                kwargs["addr"],
                kwargs["mount_path"],
                kwargs["auth_method"],
            )
        else:
            kwargs = self._auth_redis_kwargs(args)
            if args.store == "redis":
                # host/port/db are safe to log; the password never is.
                log.debug(
                    "Redis: %s:%s (db=%s)",
                    kwargs["redis_host"],
                    kwargs["redis_port"],
                    kwargs["redis_db"],
                )
        store, _shared = create_key_store(store_type=args.store, **kwargs)
        return store

    def _store_call(
        self, args: Any, method_name: str, *call_args: Any
    ) -> Tuple[Optional[Any], Optional[Any], Optional[str]]:
        """
        Create the store and run one async method against it.

        Returns ``(store, result, error)`` — on success *error* is ``None``,
        on failure *store*/*result* are ``None`` and *error* carries the
        user-facing message.
        """
        started = time.perf_counter()
        try:
            store = self._make_store(args)
            log.debug("Store call: %s", self._describe_call(method_name, call_args))
            result = asyncio.run(getattr(store, method_name)(*call_args))
            log.debug(
                "Store call %s ok in %.3fs",
                method_name,
                time.perf_counter() - started,
            )
            return store, result, None
        except (ValueError, RuntimeError, OSError) as exc:
            log.debug(
                "Store call %s failed after %.3fs: %s",
                method_name,
                time.perf_counter() - started,
                exc,
            )
            return None, None, str(exc)

    #: Arg-dict keys that are secrets and must never appear in logs.
    _SECRET_ARG_KEYS = frozenset(
        {"key_plain", "key", "secret", "secret_id", "token", "password"}
    )

    @classmethod
    def _describe_call(cls, method_name: str, call_args: Sequence[Any]) -> str:
        """A log-friendly, secret-safe description of a store call."""
        rendered = []
        for arg in call_args:
            if isinstance(arg, dict):
                safe = {
                    k: ("***" if k in cls._SECRET_ARG_KEYS else v)
                    for k, v in arg.items()
                }
                rendered.append(repr(safe))
            else:
                rendered.append(repr(arg))
        return f"{method_name}({', '.join(rendered)})"

    @staticmethod
    def _persist_seeds(store: Any) -> None:
        """Persist the seed file when the store supports it (memory backend)."""
        if store is not None and hasattr(store, "_persist_seeds"):
            seed_file = getattr(store, "_seed_file", None)
            if seed_file:
                store._persist_seeds(seed_file)

    # ------------------------------------------------------------------ #
    # Rate-limit preset loading
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_presets(raw: Any) -> Optional[List[Dict[str, Any]]]:
        """
        Parse raw preset JSON, returning ``None`` when it is invalid, not a
        list, or contains no usable presets.
        """
        try:
            presets = json.loads(raw)
        except (json.JSONDecodeError, TypeError, OSError):
            return None
        if not isinstance(presets, list):
            return None
        valid = [p for p in presets if isinstance(p, dict) and "name" in p]
        return valid or None

    @classmethod
    def _read_presets_file(cls, path: Path) -> Optional[List[Dict[str, Any]]]:
        """Load presets from *path*, or ``None`` when unreadable/invalid."""
        try:
            return cls._parse_presets(path.read_bytes())
        except OSError:
            return None

    @classmethod
    def _package_presets(cls) -> Optional[bytes]:
        """Return the packaged preset JSON bytes, or ``None`` if unavailable."""
        try:
            from importlib import resources as pkg_resources

            return (
                pkg_resources.files("llm_router_cli.resources.configs")
                .joinpath(cls.PRESET_FILE_NAME)
                .read_bytes()
            )
        except (ImportError, OSError, AttributeError):
            # intentional: packaged preset missing/unreadable — the callers
            # fall back to the next candidate in their chain.
            return None

    @classmethod
    def _seed_policies(cls, config_dir: Path) -> None:
        """
        Copy the shipped presets into *config_dir* when they do not exist yet.
        """
        dest = config_dir / cls.PRESET_FILE_NAME
        if dest.exists():
            return
        data = cls._package_presets()
        if data is None:
            fallback = Path("resources/configs") / cls.PRESET_FILE_NAME
            if fallback.is_file():
                data = fallback.read_bytes()
        if data is not None:
            dest.write_bytes(data)

    @classmethod
    def _load_rate_limit_presets(cls) -> List[Dict[str, Any]]:
        """
        Load predefined rate-limit presets.

        Resolution order: the ``LLM_ROUTER_RATE_LIMITING_CONFIG`` path (file
        or directory), the user config file, the packaged resource, and
        finally the builtin presets.
        """
        candidates: List[Path] = []
        env_path = os.environ.get("LLM_ROUTER_RATE_LIMITING_CONFIG", "").strip()
        if env_path:
            env_dir = Path(env_path)
            candidates.append(env_dir)
            candidates.append(env_dir / cls.PRESET_FILE_NAME)
        candidates.append(
            Path.home() / ".llm-router" / "configs" / cls.PRESET_FILE_NAME
        )

        for path in candidates:
            presets = cls._read_presets_file(path)
            if presets is not None:
                return presets

        package_bytes = cls._package_presets()
        if package_bytes is not None:
            presets = cls._parse_presets(package_bytes)
            if presets is not None:
                return presets

        return cls._BUILTIN_RATE_LIMIT_PRESETS

    # ------------------------------------------------------------------ #
    # Subparser registration
    # ------------------------------------------------------------------ #
    @classmethod
    def _register_key(cls, subparsers: "argparse._SubParsersAction[Any]") -> None:
        """Register the ``key`` sub-subcommands under *subparsers*."""
        key_parser = subparsers.add_parser(cls.KEY_NAME, help="Manage API keys")
        key_sub = key_parser.add_subparsers(dest="key_command")

        generate_p = key_sub.add_parser("generate", help="Generate a new API key")
        cls._add_store_and_redis_args(generate_p)
        generate_p.add_argument(
            "--policy",
            default="developer",
            help="Policy name to assign to the new key",
        )
        generate_p.add_argument(
            "--expires",
            type=str,
            default=None,
            help="Expiry time (Unix timestamp; omit for no expiry)",
        )
        generate_p.add_argument(
            "--output",
            type=str,
            default=None,
            help="Write the generated key to a file instead of stdout",
        )

        list_p = key_sub.add_parser("list", help="List all API keys")
        cls._add_store_and_redis_args(list_p)
        list_p.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Output in JSON format",
        )

        for name, help_text in (
            ("delete", "Delete an API key"),
            ("disable", "Disable an API key (deactivate without deleting)"),
            ("enable", "Re-enable a previously disabled API key"),
        ):
            sub = key_sub.add_parser(name, help=help_text)
            cls._add_key_id_arg(sub)
            cls._add_store_and_redis_args(sub)

        rotate_p = key_sub.add_parser("rotate", help="Rotate an API key")
        cls._add_key_id_arg(rotate_p)
        cls._add_store_and_redis_args(rotate_p)
        rotate_p.add_argument(
            "--grace",
            type=int,
            default=3600,
            help="Grace period in seconds (default: 3600)",
        )

    @classmethod
    def _register_policy(cls, subparsers: "argparse._SubParsersAction[Any]") -> None:
        """Register the ``policy`` sub-subcommands under *subparsers*."""
        policy_parser = subparsers.add_parser(
            cls.POLICY_NAME, help="Manage policies"
        )
        policy_sub = policy_parser.add_subparsers(dest="policy_command")
        policy_sub.add_parser("list", help="List available policies")
        policy_create = policy_sub.add_parser("create", help="Create a new policy")
        policy_create.add_argument("name", help="Policy name")
        policy_create.add_argument("policy_json", help="JSON policy definition")
        cls._add_store_and_redis_args(policy_create)

    @classmethod
    def register_rate_limit_subparser(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """
        Register the ``rate-limit`` sub-subcommands under *subparsers*.
        """
        rl_parser = subparsers.add_parser(
            cls.RATE_LIMIT_NAME,
            help="Manage rate limiting presets and per-key overrides",
        )
        rl_sub = rl_parser.add_subparsers(dest="rate_limit_command")
        rl_sub.add_parser("list", help="List available rate-limit presets")
        rl_apply = rl_sub.add_parser(
            "apply", help="Apply a rate-limit preset to an existing key"
        )
        cls._add_key_id_arg(rl_apply)
        rl_apply.add_argument("--preset", required=True, help="Preset name")
        cls._add_store_and_redis_args(rl_apply)
        rl_remove = rl_sub.add_parser(
            "remove",
            help="Remove rate-limit override from a key (revert to global default)",
        )
        cls._add_key_id_arg(rl_remove)
        cls._add_store_and_redis_args(rl_remove)

    @classmethod
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the ``auth`` leaf sub‑commands (key / policy / rate-limit)."""
        cls._register_key(subparsers)
        cls._register_policy(subparsers)
        cls.register_rate_limit_subparser(subparsers)

    # ------------------------------------------------------------------ #
    # Dispatch
    # ------------------------------------------------------------------ #
    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Dispatch an already-parsed *args* namespace (no re-parsing)."""
        auth_command = getattr(args, cls.SUBPARSER_DEST, None)
        if auth_command is None:
            cls.build_parser().print_help()
            return 0

        cls._ensure_seed_env()
        self = cls()
        handler = {
            cls.KEY_NAME: self._handle_key,
            cls.POLICY_NAME: self._handle_policy,
            cls.RATE_LIMIT_NAME: self._handle_rate_limit,
        }.get(auth_command)
        if handler is None:
            cls.build_parser().print_help()
            return 1
        setup_logging(verbose=bool(getattr(args, "verbose", False)))
        return handler(args)

    # ------------------------------------------------------------------ #
    # Key handlers
    # ------------------------------------------------------------------ #
    def _handle_key(self, args: Any) -> int:
        """Route key subcommands to their handlers (mutations share one path)."""
        cmd = getattr(args, "key_command", None)
        if cmd is None:
            return self._fail(
                f"Usage: llm-router auth key <{'|'.join(self.KEY_COMMANDS)}>"
            )

        if cmd in self.KEY_MUTATE_ACTIONS:
            return self._key_mutate(args, cmd)

        handler = {
            "generate": self._key_generate,
            "list": self._key_list,
            "rotate": self._key_rotate,
        }.get(cmd)
        if handler is None:
            return self._fail(f"Unknown key command: {cmd}")
        return handler(args)

    def _key_generate(self, args: Any) -> int:
        """
        Handle the ``generate`` subcommand.
        """
        from llm_router_api.core.auth.key_generator import KeyGenerator
        from llm_router_api.core.auth.policies.builtin import get_builtin_policy

        policy = args.policy
        if get_builtin_policy(policy) is None:
            return self._fail(f"Policy '{policy}' does not exist.")

        expires: Optional[float] = None
        if args.expires not in (None, ""):
            try:
                expires = float(args.expires)
            except ValueError:
                return self._fail(
                    f"--expires must be a Unix timestamp (got '{args.expires}')."
                )

        log.debug("Generating key (policy=%s, expires=%s)", policy, expires)
        record = {
            "key_plain": KeyGenerator().generate(),
            "policy_name": policy,
            "expires_at": expires,
            "metadata": {},
        }
        _store, plaintext_key, error = self._store_call(args, "create_key", record)
        if error is not None or plaintext_key is None:
            return self._fail(error or "key generation failed")

        if args.output:
            out_path = Path(args.output).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(plaintext_key + "\n", encoding="utf-8")
            print(f"Generated key for policy '{policy}' written to {out_path}")
        else:
            print(f"Generated key for policy '{policy}':")
            print(plaintext_key)
        print("⚠️  This key is displayed ONCE. Store it securely!")
        print(f"Expires at: {expires}")
        print(f"Policy: {policy}")
        return 0

    def _key_list(self, args: Any) -> int:
        """
        Handle the ``list`` subcommand.
        """
        _store, keys, error = self._store_call(args, "list_keys")
        if error is not None:
            return self._fail(error)

        log.debug("Listed %d key(s)", len(keys or []))
        if not keys:
            print("No API keys found.")
            return 0

        if getattr(args, "json", False):
            print(json.dumps(keys, indent=2))
            return 0

        rows = [
            (
                k["key_id"],
                k.get("key_prefix", ""),
                k.get("policy_name", ""),
                "yes" if k.get("is_active") else "no",
                f"{k['expires_at']:.0f}" if k.get("expires_at") else "none",
            )
            for k in keys
        ]
        print(
            self._render_table(
                ("KEY_ID", "PREFIX", "POLICY", "ACTIVE", "EXPIRES"),
                rows,
                min_widths=(8, 8, 8, 7, 10),
                gap=" ",
            )
        )
        return 0

    def _key_mutate(self, args: Any, action: str) -> int:
        """
        Shared handler for the ``delete`` / ``disable`` / ``enable``
        subcommands — they share the same flow.
        """
        store, _result, error = self._store_call(args, f"{action}_key", args.key_id)
        if error is not None:
            return self._fail(error)

        self._persist_seeds(store)
        past_tense = "deleted" if action == "delete" else f"{action}d"
        print(f"Key {args.key_id} {past_tense}.")
        return 0

    def _key_rotate(self, args: Any) -> int:
        """
        Handle the ``rotate`` subcommand.
        """
        log.debug("Rotating key %s (grace=%ss)", args.key_id, args.grace)
        store, new_key, error = self._store_call(
            args, "rotate_key", args.key_id, args.grace
        )
        if error is not None:
            return self._fail(error)

        self._persist_seeds(store)
        print(f"Rotated key {args.key_id} -> new key:")
        print(new_key)
        print("\n⚠️  This key is displayed ONCE. Store it securely!")
        return 0

    # ------------------------------------------------------------------ #
    # Policy handlers
    # ------------------------------------------------------------------ #
    def _handle_policy(self, args: Any) -> int:
        """
        Handle policy subcommands.
        """
        cmd = getattr(args, "policy_command", None)
        if cmd is None:
            return self._fail("Usage: llm-router auth policy <list|create> ...")

        if cmd == "list":
            from llm_router_api.core.auth.policies.builtin import (
                list_builtin_policies,
            )

            print("Builtin policies:")
            for name in list_builtin_policies():
                print(f"  {name}")
            return 0

        if cmd == "create":
            from llm_router_api.core.auth.policies.model import EndpointPolicy
            from llm_router_api.core.auth.policies.builtin import register_policy

            try:
                policy_dict = json.loads(args.policy_json)
            except json.JSONDecodeError as exc:
                return self._fail(f"Invalid JSON: {exc}")
            try:
                register_policy(args.name, EndpointPolicy(**policy_dict))
            except (TypeError, ValueError) as exc:
                return self._fail(f"Invalid policy definition: {exc}")
            print(f"Policy '{args.name}' created.")
            return 0

        return self._fail(f"Unknown policy command: {cmd}")

    # ------------------------------------------------------------------ #
    # Rate-limit handlers
    # ------------------------------------------------------------------ #
    def _handle_rate_limit(self, args: Any) -> int:
        """
        Handle rate-limit subcommands.
        """
        cmd = getattr(args, "rate_limit_command", None)
        if cmd is None:
            return self._fail(
                "Usage: llm-router auth rate-limit <list|apply|remove> ..."
            )
        handler = {
            "list": self._rl_list,
            "apply": self._rl_apply,
            "remove": self._rl_remove,
        }.get(cmd)
        if handler is None:
            return self._fail(f"Unknown rate-limit command: {cmd}")
        return handler(args)

    @staticmethod
    def _preset_rpm(preset: Dict[str, Any]) -> str:
        """Human-readable rate-limit cell for *preset* (per-minute or per-day)."""
        if preset.get("rpm"):
            return str(preset["rpm"])
        return f"{preset.get('daily_limit', 'N/A')}/day"

    def _rl_list(self, args: Any) -> int:
        """
        List all available rate-limit presets.
        """
        presets = self._load_rate_limit_presets()
        if not presets:
            print("No presets found.")
            return 1

        rows = [
            (p["name"], self._preset_rpm(p), p.get("description", ""))
            for p in presets
        ]
        print("Available rate-limit presets:")
        print(
            self._render_table(
                ("NAME", "RPM", "DESCRIPTION"), rows, aligns=("l", "r", "l")
            )
        )
        return 0

    def _resolve_rate_limit_preset(self, preset_name: str) -> Optional[int]:
        """
        Resolve a preset name to a per-minute rate limit (or ``None``).
        """
        presets = self._load_rate_limit_presets()
        preset = next((p for p in presets if p["name"] == preset_name), None)
        if preset is None:
            return None
        rate_limit = preset.get("rpm")
        daily_limit = preset.get("daily_limit")
        if rate_limit is None and daily_limit is not None:
            rate_limit = max(1, daily_limit // 1440)
        return rate_limit

    def _rl_apply(self, args: Any) -> int:
        """
        Apply a rate-limit preset to an existing key (any store backend).
        """
        rate_limit = self._resolve_rate_limit_preset(args.preset)
        if rate_limit is None:
            names = ", ".join(p["name"] for p in self._load_rate_limit_presets())
            return self._fail(f"Unknown preset '{args.preset}'. Available: {names}")

        _store, _result, error = self._store_call(
            args, "update_policy_override", args.key_id, rate_limit
        )
        if error is not None:
            return self._fail(error)

        print(
            f"Applied preset '{args.preset}' "
            f"(rate_limit='{rate_limit}'/min) to key {args.key_id}."
        )
        return 0

    def _rl_remove(self, args: Any) -> int:
        """
        Remove the rate-limit override from a key (any store backend).
        """
        _store, _result, error = self._store_call(
            args, "update_policy_override", args.key_id, None
        )
        if error is not None:
            return self._fail(error)

        print(
            f"Removed rate-limit override for key {args.key_id} "
            f"(will use global default)."
        )
        return 0
