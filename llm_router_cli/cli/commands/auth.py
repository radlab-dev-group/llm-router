"""
CLI commands for API key management.

Usage::

    llm-router auth key generate [--policy developer] [--store memory]
    llm-router auth key list [--store memory]
    llm-router auth key delete <key-id> [--store memory]
    llm-router auth key disable <key-id> [--store memory]
    llm-router auth key enable <key-id> [--store memory]
    llm-router auth key rotate <key-id> [--grace 3600]
    llm-router auth key reveal <key-id>
    llm-router auth policy list
    llm-router auth policy create <name> <json-policy>
    llm-router auth rate-limit list
    llm-router auth rate-limit apply <key-id> --preset <name> [--store memory]
    llm-router auth rate-limit remove <key-id> [--store memory]
"""

from __future__ import annotations

import os
import sys
import json
import asyncio
import argparse
from typing import Any

from pathlib import Path


class AuthCommand:
    """Encapsulates the ``auth`` CLI subcommand and all its children.

    Public API (exactly two methods):
      - :meth:`register_parser`  – register *auth* under a parent argparse parser.
      - :meth:`run`             – standalone entry point; parse + dispatch.
    """

    NAME = "auth"
    KEY_NAME = "key"
    POLICY_NAME = "policy"
    RATE_LIMIT_NAME = "rate-limit"
    STORE_BACKENDS = ["memory", "redis", "vault"]

    SEED_DIR = Path.home() / ".llm-router"
    DEFAULT_SEED_FILE = str(SEED_DIR / "configs" / "auth" / "memory-keys.json")

    # ---- Built-in rate-limit presets (class-level constant) ---------------

    _BUILTIN_RATE_LIMIT_PRESETS: list[dict] = [
        {"name": "free", "rpm": 10, "description": "Free tier — limited usage"},
        {"name": "basic", "rpm": 60, "description": "Standard (1/s)"},
        {"name": "pro", "rpm": 120, "description": "Pro tier (2/s)"},
        {"name": "enterprise", "rpm": 500, "description": "High throughput"},
    ]

    # ---- Key command dispatch table (class-level constant) -----------------

    _KEY_COMMANDS: dict[str, str] = {
        "generate": "_key_generate",
        "list": "_key_list",
        "delete": "_key_mutate_delete",
        "disable": "_key_mutate_disable",
        "enable": "_key_mutate_enable",
        "rotate": "_key_rotate",
        "reveal": "_key_reveal",
    }

    # ---- Argument-adding helpers -------------------------------------------

    @staticmethod
    def _add_store_and_redis_args(p: argparse.ArgumentParser) -> None:
        """Add ``--store`` and all ``--auth-redis-*`` flags to *p*."""
        p.add_argument(
            "--store",
            default="memory",
            choices=AuthCommand.STORE_BACKENDS,
            help="Key store backend",
        )
        p.add_argument(
            "--auth-redis-host",
            default=None,
            help="Redis host for auth key store (default: env LLM_ROUTER_AUTH_REDIS_HOST)",
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

    @staticmethod
    def _add_key_id_arg(p: argparse.ArgumentParser) -> None:
        """Add the positional ``key_id`` argument to *p*."""
        p.add_argument("key_id", help="Key ID to operate on")

    # ---- Seed / store setup -----------------------------------------------

    @classmethod
    def _ensure_seed_env(cls) -> str:
        """Ensure seed directory structure and return the seed file path."""
        cls.SEED_DIR.mkdir(exist_ok=True)
        auth_dir = cls.SEED_DIR / "configs" / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        cls._seed_policies(cls.SEED_DIR / "configs")
        return cls.DEFAULT_SEED_FILE

    @classmethod
    def _seed_policies(cls, config_dir: Path) -> None:
        """Copy the shipped policies JSON into *config_dir* when it does not exist yet."""
        dest = config_dir / "rate_limiting-policies.json"
        if dest.exists():
            return
        try:
            from importlib import resources as pkg_resources

            src_data = (
                pkg_resources.files("llm_router_cli.resources.configs")
                .joinpath("rate_limiting-policies.json")
                .read_bytes()
            )
            dest.write_bytes(src_data)
            return
        except (ImportError, OSError):
            pass
        fallback = Path("resources/configs/rate_limiting-policies.json")
        if fallback.is_file():
            dest.write_text(fallback.read_text(encoding="utf-8"))

    # ---- Key-store / Redis helpers ----------------------------------------

    @staticmethod
    def _auth_redis_kwargs(args) -> dict:
        """Build redis kwargs for auth key store (CLI args → env vars → defaults)."""
        return {
            "redis_host": getattr(args, "auth_redis_host", None)
            or os.environ.get("LLM_ROUTER_AUTH_REDIS_HOST"),
            "redis_port": int(
                getattr(args, "auth_redis_port", 0)
                or os.environ.get("LLM_ROUTER_AUTH_REDIS_PORT", 6379)
            ),
            "redis_db": int(
                getattr(args, "auth_redis_db", -1)
                or os.environ.get("LLM_ROUTER_AUTH_REDIS_DB", 0)
            ),
            "redis_password": (
                getattr(args, "auth_redis_password", None)
                or os.environ.get("LLM_ROUTER_AUTH_REDIS_PASSWORD")
            )
            or None,
        }

    @staticmethod
    def _extract_key_id(argv: list[str]) -> str | None:
        """Extract the positional key ID from argv (first non-flag token)."""
        for arg in argv:
            if not arg.startswith("-"):
                return arg
        return None

    @classmethod
    def _make_redis_client(cls, redis_kwargs: dict) -> Any:
        """Create and return a Redis client from *redis_kwargs* with env fallbacks."""
        import redis as _redis_mod

        host = redis_kwargs.get("redis_host") or os.environ.get(
            "LLM_ROUTER_AUTH_REDIS_HOST", "127.0.0.1"
        )
        port = int(
            redis_kwargs.get("redis_port")
            or os.environ.get("LLM_ROUTER_AUTH_REDIS_PORT", 6379)
        )
        db = int(
            redis_kwargs.get("redis_db")
            or os.environ.get("LLM_ROUTER_AUTH_REDIS_DB", 0)
        )
        password = redis_kwargs.get("redis_password") or os.environ.get(
            "LLM_ROUTER_AUTH_REDIS_PASSWORD"
        )
        return _redis_mod.Redis(
            host=host, port=port, db=db, decode_responses=True, password=password
        )

    @classmethod
    def _read_seed_keys(cls) -> tuple[list | None, int]:
        """Read and validate the seed file. Returns ``(keys_list, 0)`` or ``(None, 1)``."""
        seed_file = cls.DEFAULT_SEED_FILE
        seed_path = Path(seed_file)
        if not seed_path.exists():
            print(f"Error: Seed file {seed_file} does not exist.")
            return None, 1
        keys = json.loads(seed_path.read_text(encoding="utf-8"))
        if not isinstance(keys, list):
            print("Error: Seed file must contain a JSON array.")
            return None, 1
        return keys, 0

    # ---- Rate-limit preset loading ----------------------------------------

    @classmethod
    def _load_rate_limit_presets(cls) -> list[dict]:
        """
        Load predefined rate-limit presets
        (env var → user config → package resource → builtin).
        """
        env_path = os.environ.get("LLM_ROUTER_RATE_LIMITING_CONFIG", "").strip()

        def _try_load(path: Path) -> list[dict] | None:
            if not path.exists():
                return None
            try:
                presets = json.loads(path.read_text(encoding="utf-8"))
                result = [p for p in presets if isinstance(p, dict) and "name" in p]
                return result if result else None
            except (json.JSONDecodeError, OSError):
                return None

        def _try_load_bytes(data: bytes) -> list[dict] | None:
            try:
                presets = json.loads(data)
                result = [p for p in presets if isinstance(p, dict) and "name" in p]
                return result if result else None
            except (json.JSONDecodeError, OSError):
                return None

        if env_path:
            candidate = Path(env_path)
            loaded = _try_load(candidate)
            if loaded is not None:
                return loaded
            loaded = _try_load(candidate / "rate_limiting-policies.json")
            if loaded is not None:
                return loaded

        user_config = (
            Path.home() / ".llm-router" / "configs" / "rate_limiting-policies.json"
        )
        loaded = _try_load(user_config)
        if loaded is not None:
            return loaded

        try:
            from importlib import resources as pkg_resources

            _PACKAGE_RES = (
                pkg_resources.files("llm_router_cli.resources.configs")
                / "rate_limiting-policies.json"
            )
            if hasattr(_PACKAGE_RES, "read_bytes"):
                loaded = _try_load_bytes(_PACKAGE_RES.read_bytes())
            elif hasattr(_PACKAGE_RES, "joinpath"):
                loaded = _try_load(Path(_PACKAGE_RES))
            if loaded is not None:
                return loaded
        except (ImportError, OSError):
            pass

        return cls._BUILTIN_RATE_LIMIT_PRESETS

    # ---- Subparser registration -------------------------------------------

    @classmethod
    def register_rate_limit_subparser(cls, parser: argparse.ArgumentParser) -> None:
        """Register the ``rate-limit`` sub-subcommands under *parser*."""
        rl_parser = parser.add_parser(
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
    def register_parser(
        cls,
        parser: argparse.ArgumentParser | argparse._SubParsersAction,
        nest_auth: bool = True,
    ) -> None:
        """Register the ``auth`` subparser with its child commands."""
        if nest_auth:
            auth_parser = parser.add_parser(
                cls.NAME, help="Manage API keys and authentication"
            )
            auth_sub = auth_parser.add_subparsers(dest="auth_command")
        else:
            auth_sub = parser

        key_parser = auth_sub.add_parser(cls.KEY_NAME, help="Manage API keys")
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
            help="Expiry time (Unix timestamp or None for no expiry)",
        )
        generate_p.add_argument(
            "--output",
            type=str,
            default=None,
            help="Output file path (default: stdout)",
        )

        list_p = key_sub.add_parser("list", help="List all API keys")
        cls._add_store_and_redis_args(list_p)
        list_p.add_argument(
            "--json",
            action="store_true",
            default=False,
            help="Output in JSON format",
        )
        list_p.add_argument(
            "--reveal",
            action="store_true",
            default=False,
            help="Reveal plaintext keys (memory store only)",
        )

        for name, help_text in [
            ("delete", "Delete an API key"),
            ("disable", "Disable an API key (deactivate without deleting)"),
            ("enable", "Re-enable a previously disabled API key"),
        ]:
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

        reveal_p = key_sub.add_parser(
            "reveal", help="Reveal a key (only available in memory store)"
        )
        cls._add_key_id_arg(reveal_p)
        cls._add_store_and_redis_args(reveal_p)

        policy_parser = auth_sub.add_parser(cls.POLICY_NAME, help="Manage policies")
        policy_sub = policy_parser.add_subparsers(dest="policy_command")
        policy_sub.add_parser("list", help="List available policies")
        policy_create = policy_sub.add_parser("create", help="Create a new policy")
        policy_create.add_argument("name", help="Policy name")
        policy_create.add_argument("policy_json", help="JSON policy definition")
        cls._add_store_and_redis_args(policy_create)

        cls.register_rate_limit_subparser(auth_sub)

    # ---- Public run() entry point -----------------------------------------

    @classmethod
    def run(cls, argv: list[str] | None = None) -> int:
        """Standalone entry point: parse args and dispatch to handlers."""
        if argv is None:
            argv = sys.argv[1:]

        parser = argparse.ArgumentParser(
            description="Manage API keys and authentication"
        )
        auth_sub = parser.add_subparsers(dest="auth_command")
        parser.add_argument(
            "--store",
            default="memory",
            choices=cls.STORE_BACKENDS,
            help="Key store backend (default: memory)",
        )
        cls.register_parser(auth_sub, nest_auth=False)  # type: ignore[arg-type]
        args = parser.parse_args(argv)

        if args.auth_command is None or not argv:
            parser.print_help()
            return 0

        cmd = argv[0]
        sub = argv[1:] if len(argv) > 1 else []
        seed_file = cls._ensure_seed_env()

        if cmd == "key":
            return cls()._handle_key(args, sub, seed_file)
        if cmd == "policy":
            return cls()._handle_policy(args, sub)
        if cmd == "rate-limit":
            return cls()._handle_rate_limit(sub)
        parser.print_help()
        return 1

    # ---- Key handler commands (all private methods on the class) ----------

    def _handle_key(self, args, sub: list[str], seed_file: str) -> int:
        """Route key subcommands via the dispatch table."""
        if not sub:
            print(f"Usage: llm-router auth key <{'|'.join(self._KEY_COMMANDS)}>")
            return 1

        cmd = sub[0]
        key_args = sub[1:]
        handler_method_name = self._KEY_COMMANDS.get(cmd)
        if handler_method_name is None:
            print(f"Unknown key command: {cmd}")
            return 1

        # delete/disable/enable — create their own store inline via _key_action
        if cmd in ("delete", "disable", "enable"):
            key_id = self._extract_key_id(key_args)
            if not key_id:
                print(f"Error: key_id is required for {cmd}.")
                return 1
            from llm_router_api.core.auth.key_store import create_key_store

            key_store, _ = create_key_store(
                store_type=getattr(args, "store", "memory"),
                **self._auth_redis_kwargs(args),
            )
            return self._key_action(key_store, key_id, cmd, seed_file=seed_file)

        # Other handlers receive (args, key_args).
        handler = getattr(self, handler_method_name)
        return handler(args, key_args)

    def _key_generate(self, args, key_args) -> int:
        """Handle the 'generate' subcommand."""
        from llm_router_api.core.auth.key_generator import KeyGenerator
        from llm_router_api.core.auth.key_store import create_key_store
        from llm_router_api.core.auth.policies.builtin import get_builtin_policy

        gen = KeyGenerator()
        policy = "developer"
        expires: float | None = None
        for i, arg in enumerate(key_args):
            if arg == "--policy" and i + 1 < len(key_args):
                policy = key_args[i + 1]
            elif arg == "--expires" and i + 1 < len(key_args):
                expires = float(key_args[i + 1])

        policy_obj = get_builtin_policy(policy)
        if policy_obj is None:
            print(f"Error: Policy '{policy}' does not exist.")
            return 1

        key_store, _ = create_key_store(
            store_type=args.store, **self._auth_redis_kwargs(args)
        )
        record = {
            "key_plain": gen.generate(),
            "policy_name": policy,
            "expires_at": expires,
            "metadata": {},
        }
        plaintext_key = asyncio.run(key_store.create_key(record))

        print(f"Generated key for policy '{policy}':")
        print(plaintext_key)
        print("\n⚠️  This key is displayed ONCE. Store it securely!")
        print(f"Expires at: {expires}")
        print(f"Policy: {policy}")
        return 0

    def _key_list(self, args, key_args) -> int:
        """Handle the 'list' subcommand."""
        from llm_router_api.core.auth.key_store import create_key_store

        key_store, _ = create_key_store(
            store_type=args.store, **self._auth_redis_kwargs(args)
        )
        show_plain = getattr(args, "reveal", False)
        keys = asyncio.run(key_store.list_keys())
        if not keys:
            print("No API keys found.")
            return 0

        max_w: dict[str, int] = {
            "KEY_ID": 8,
            "PREFIX": 8,
            "POLICY": 8,
            "ACTIVE": 7,
            "EXPIRES": 10,
        }
        for k in keys:
            exp_str = (
                f"{k.get('expires_at', 'none'):.0f}"
                if k.get("expires_at")
                else "none"
            )
            max_w["KEY_ID"] = max(max_w["KEY_ID"], len(k["key_id"]) + 1)
            max_w["PREFIX"] = max(max_w["PREFIX"], len(k.get("key_prefix", "")) + 1)
            max_w["POLICY"] = max(max_w["POLICY"], len(k.get("policy_name", "")) + 1)
            max_w["ACTIVE"] = max(max_w["ACTIVE"], 4 + 1)

        w = (
            max_w["KEY_ID"],
            max_w["PREFIX"],
            max_w["POLICY"],
            max_w["ACTIVE"],
            max_w["EXPIRES"],
        )
        hdr = (
            f"{'KEY_ID':<{w[0]}} {'PREFIX':<{w[1]}} {'POLICY':<{w[2]}} "
            f"{'ACTIVE':<{w[3]}} {'EXPIRES':<{w[4]}}"
        )
        print(hdr)
        print("-" * len(hdr))

        for k in keys:
            exp_str = (
                f"{k.get('expires_at', 'none'):.0f}"
                if k.get("expires_at")
                else "none"
            )
            line = (
                f"{k['key_id']:<{w[0]}} {k['key_prefix']:<{w[1]}} {k['policy_name']:<{w[2]}} "
                f"{'yes' if k.get('is_active') else 'no':<{w[3]}} {exp_str:<{w[4]}}"
            )
            if show_plain and "key_plain" in k:
                line += f"  PLAIN: {k['key_plain']}"
            print(line)
        return 0

    def _key_action(
        self, key_store, key_id: str, action: str, *, seed_file=None
    ) -> int:
        """Handle delete / disable / enable — they share the same flow."""
        method_name = f"{action}_key"
        success_msg = (
            f"Key {key_id} {'deleted' if action == 'delete' else action + 'd'}."
        )
        try:
            method = getattr(key_store, method_name)
            asyncio.run(method(key_id))
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1

        if hasattr(key_store, "_persist_seeds"):
            target = seed_file or getattr(key_store, "_seed_file", None)
            if target:
                key_store._persist_seeds(target)

        print(success_msg)
        return 0

    def _key_mutate_delete(self, args, key_args) -> int:
        """dispatch → _key_mutate with action='delete'."""
        return self._key_mutate(args, key_args, "delete")

    def _key_mutate_disable(self, args, key_args) -> int:
        """dispatch → _key_mutate with action='disable'."""
        return self._key_mutate(args, key_args, "disable")

    def _key_mutate_enable(self, args, key_args) -> int:
        """dispatch → _key_mutate with action='enable'."""
        return self._key_mutate(args, key_args, "enable")

    def _key_mutate(self, args, key_args: list[str], action: str) -> int:
        """Shared dispatcher for delete / disable / enable."""
        key_id = self._extract_key_id(key_args)
        if not key_id:
            print(f"Error: key_id is required for {action}.")
            return 1

        from llm_router_api.core.auth.key_store import create_key_store

        key_store, _ = create_key_store(
            store_type=args.store, **self._auth_redis_kwargs(args)
        )
        seed_file = getattr(key_store, "_seed_file", None)
        return self._key_action(key_store, key_id, action, seed_file=seed_file)

    def _key_rotate(self, args, key_args) -> int:
        """Handle the 'rotate' subcommand."""
        from llm_router_api.core.auth.key_store import create_key_store

        key_id = self._extract_key_id(key_args)
        if not key_id:
            print("Error: key_id is required for rotate.")
            return 1

        grace = 3600
        for i, arg in enumerate(key_args):
            if arg == "--grace" and i + 1 < len(key_args):
                grace = int(key_args[i + 1])

        key_store, _ = create_key_store(
            store_type=args.store, **self._auth_redis_kwargs(args)
        )
        seed_file = getattr(key_store, "_seed_file", None)
        new_key = asyncio.run(key_store.rotate_key(key_id, grace))
        if hasattr(key_store, "_persist_seeds") and seed_file:
            key_store._persist_seeds(seed_file)

        print(f"Rotated key {key_id} -> new key:")
        print(new_key)
        print("\n⚠️  This key is displayed ONCE. Store it securely!")
        return 0

    def _key_reveal(self, args, key_args) -> int:
        """Handle the 'reveal' subcommand."""
        from llm_router_api.core.auth.key_store import create_key_store

        key_id = self._extract_key_id(key_args)
        if not key_id:
            print("Error: key_id is required for reveal.")
            return 1

        key_store, _ = create_key_store(
            store_type=args.store, **self._auth_redis_kwargs(args)
        )
        record = asyncio.run(key_store.get_key_by_id(key_id))
        if not record:
            print(f"Key {key_id} not found.")
            return 1

        plain = record.get("key_plain")
        if plain:
            print(f"Key {key_id}:")
            print(plain)
        else:
            print(f"Key {key_id} hash: {record.get('key_hash', 'N/A')}")
        return 0

    # ---- Policy handler ---------------------------------------------------

    def _handle_policy(self, args, sub: list[str]) -> int:
        """Handle policy subcommands."""
        from llm_router_api.core.auth.policies.engine import EndpointPolicy
        from llm_router_api.core.auth.policies.builtin import (
            list_builtin_policies,
            register_policy,
        )

        if not sub:
            print("Usage: llm-router auth policy <list|create> ...")
            return 1

        cmd = sub[0]
        if cmd == "list":
            print("Builtin policies:")
            for name in list_builtin_policies():
                print(f"  {name}")
            return 0

        if cmd == "create":
            if len(sub) < 3:
                print("Usage: llm-router auth policy create <name> <json-policy>")
                return 1
            name, policy_json = sub[1], sub[2]
            try:
                policy_dict = json.loads(policy_json)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON: {e}")
                return 1

            register_policy(name, EndpointPolicy(**policy_dict))
            print(f"Policy '{name}' created.")
            return 0

        print(f"Unknown policy command: {cmd}")
        return 1

    # ---- Rate-limit handler -----------------------------------------------

    def _handle_rate_limit(self, sub: list[str]) -> int:
        """Handle rate-limit subcommands."""
        if not sub:
            print("Usage: llm-router auth rate-limit <list|apply|remove> ...")
            return 1
        cmd = sub[0]
        handler_map = {
            "list": self._rl_list,
            "apply": self._rl_apply,
            "remove": self._rl_remove,
        }
        handler = handler_map.get(cmd)
        if handler is None:
            print(f"Unknown rate-limit command: {cmd}")
            return 1
        return handler(sub)

    def _rl_list(self, sub: list[str]) -> int:
        """List all available rate-limit presets."""
        presets = self._load_rate_limit_presets()
        if not presets:
            print("No presets found.")
            return 1

        max_name = max(len(p["name"]) for p in presets)
        max_rpm = max(len(str(p.get("rpm", "-"))) for p in presets)

        print("Available rate-limit presets:")
        print(f"  {'NAME':<{max_name}}  {'RPM':>{max_rpm}}  DESCRIPTION")
        print(f"  {'-' * max_name}  {'-' * max_rpm}  {'-----------'}")
        for p in presets:
            rpm = (
                str(p.get("rpm", "-"))
                if p.get("rpm")
                else f"{p.get('daily_limit', 'N/A')}/day"
            )
            print(f"  {p['name']:<{max_name}}  {rpm:>{max_rpm}}  {p['description']}")
        return 0

    def _rl_apply(self, sub: list[str]) -> int:
        """Apply a rate-limit preset to an existing key."""
        if len(sub) < 2:
            print("Usage: llm-router auth rate-limit apply <key_id> --preset <name>")
            return 1

        key_id = sub[1]
        parsed = self._rl_parser(add_preset=True).parse_args(sub[1:])
        store = getattr(parsed, "store", "memory")
        preset_name = getattr(parsed, "preset", None)
        redis_kwargs = self._auth_redis_kwargs(parsed)

        if not preset_name:
            print("Error: --preset is required.")
            return 1

        presets = self._load_rate_limit_presets()
        preset = next((p for p in presets if p["name"] == preset_name), None)
        if not preset:
            names = ", ".join(p["name"] for p in presets)
            print(f"Error: Unknown preset '{preset_name}'. Available: {names}")
            return 1

        rate_limit = preset.get("rpm")
        daily_limit = preset.get("daily_limit")
        if rate_limit is None and daily_limit is not None:
            rate_limit = max(1, daily_limit // 1440)

        if store == "memory":
            keys, err = self._read_seed_keys()
            if err:
                return err
            found = False
            for rec in keys:
                if rec.get("key_id") == key_id or rec.get(
                    "key_plain", ""
                ).startswith(key_id[:7]):
                    override = rec.get("policy_override") or {}
                    override["rate_limit"] = rate_limit
                    rec["policy_override"] = override
                    found = True
                    break
            if not found:
                print(f"Error: Key '{key_id}' not found in seed file.")
                return 1
            Path(self.DEFAULT_SEED_FILE).write_text(
                json.dumps(keys, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"Applied preset '{preset_name}' (rate_limit='{rate_limit}'/min) to key {key_id}."
            )

        elif store == "redis":
            r = self._make_redis_client(redis_kwargs)
            key_hash_key = f"auth:key:{key_id}"
            raw = r.hget(key_hash_key, "policy_override")
            policy_override = json.loads(raw) if raw else {}
            policy_override["rate_limit"] = rate_limit
            r.hset(key_hash_key, "policy_override", json.dumps(policy_override))
            print(
                f"Applied preset '{preset_name}' (rate_limit='{rate_limit}'/min) to key {key_id}."
            )

        elif store == "vault":
            print(
                "Error: 'rate-limit apply' on vault store, requires Vault API. "
                "Use seed file or --store memory."
            )
            return 1
        else:
            print(f"Error: Unknown store '{store}'.")
            return 1

        return 0

    def _rl_remove(self, sub: list[str]) -> int:
        """Remove rate-limit override from a key."""
        if len(sub) < 2:
            print("Usage: llm-router auth rate-limit remove <key_id>")
            return 1

        key_id = sub[1]
        parsed = self._rl_parser().parse_args(sub[1:])
        store = getattr(parsed, "store", "memory")
        redis_kwargs = self._auth_redis_kwargs(parsed)

        if store == "memory":
            keys, err = self._read_seed_keys()
            if err:
                return err
            found = False
            for rec in keys:
                if rec.get("key_id") == key_id or rec.get(
                    "key_plain", ""
                ).startswith(key_id[:7]):
                    if rec.get("policy_override"):
                        override = rec["policy_override"]
                        if "rate_limit" in override:
                            del override["rate_limit"]
                        if not override:
                            del rec["policy_override"]
                    found = True
                    break
            if not found:
                print(f"Error: Key '{key_id}' not found in seed file.")
                return 1
            Path(self.DEFAULT_SEED_FILE).write_text(
                json.dumps(keys, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"Removed rate-limit override for key {key_id} (will use global default)."
            )

        elif store == "redis":
            r = self._make_redis_client(redis_kwargs)
            key_hash_key = f"auth:key:{key_id}"
            raw = r.hget(key_hash_key, "policy_override")
            policy_override = json.loads(raw) if raw else {}
            if "rate_limit" in policy_override:
                del policy_override["rate_limit"]
            if not policy_override:
                r.hdel(key_hash_key, "policy_override")
            else:
                r.hset(key_hash_key, "policy_override", json.dumps(policy_override))
            print(
                f"Removed rate-limit override for key {key_id} (will use global default)."
            )

        elif store == "vault":
            print(
                "Error: 'rate-limit remove' on vault store, requires Vault API. "
                "Use seed file or --store memory."
            )
            return 1
        else:
            print(f"Error: Unknown store '{store}'.")
            return 1

        return 0

    # ---- Shared inline parser for rate-limit subcommands ------------------

    @staticmethod
    def _rl_parser(add_preset: bool = False) -> argparse.ArgumentParser:
        """Build the shared argument parser for rate-limit subcommands."""
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--store", default="memory")
        p.add_argument("--auth-redis-host", default=None)
        p.add_argument("--auth-redis-port", type=int, default=None)
        p.add_argument("--auth-redis-db", type=int, default=None)
        p.add_argument("--auth-redis-password", default=None)
        if add_preset:
            p.add_argument("--preset", default=None)
        return p
