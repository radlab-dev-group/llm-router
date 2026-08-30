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

import os
import sys
import json
import asyncio
import argparse

from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class AuthCommand:
    """
    Encapsulates the ``auth`` CLI subcommand and all its children.

    A single argparse tree is built once (see :meth:`register_parser` /
    :meth:`build_parser`) and dispatching happens **exclusively on the
    parsed namespace** — the raw argv is never re-scanned.

    Public API:
      - :meth:`register_parser` – register *auth* under a parent parser.
      - :meth:`run`             – standalone entry point (parse + dispatch).
      - :meth:`dispatch`        – dispatch an already-parsed namespace.
    """

    NAME = "auth"
    KEY_NAME = "key"
    POLICY_NAME = "policy"
    RATE_LIMIT_NAME = "rate-limit"
    STORE_BACKENDS = ["memory", "redis", "vault"]

    SEED_DIR = Path.home() / ".llm-router"
    DEFAULT_SEED_FILE = str(SEED_DIR / "configs" / "auth" / "memory-keys.json")

    # ---- Built-in rate-limit presets (class-level constant) ---------------

    _BUILTIN_RATE_LIMIT_PRESETS: List[dict] = [
        {"name": "free", "rpm": 10, "description": "Free tier — limited usage"},
        {"name": "basic", "rpm": 60, "description": "Standard (1/s)"},
        {"name": "pro", "rpm": 120, "description": "Pro tier (2/s)"},
        {"name": "enterprise", "rpm": 500, "description": "High throughput"},
    ]

    # ---- Key command dispatch table (class-level constant) -----------------

    _KEY_COMMANDS: Dict[str, str] = {
        "generate": "_key_generate",
        "list": "_key_list",
        "delete": "_key_mutate_delete",
        "disable": "_key_mutate_disable",
        "enable": "_key_mutate_enable",
        "rotate": "_key_rotate",
    }

    # ---- Argument-adding helpers -------------------------------------------

    @staticmethod
    def _add_store_and_redis_args(p: argparse.ArgumentParser) -> None:
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

    @staticmethod
    def _add_key_id_arg(p: argparse.ArgumentParser) -> None:
        """
        Add the positional ``key_id`` argument to *p*.
        """
        p.add_argument("key_id", help="Key ID to operate on")

    # ---- Seed / store setup -----------------------------------------------

    @classmethod
    def _ensure_seed_env(cls) -> str:
        """
        Ensure seed directory structure and return the seed file path.
        """
        cls.SEED_DIR.mkdir(exist_ok=True)
        auth_dir = cls.SEED_DIR / "configs" / "auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        cls._seed_policies(cls.SEED_DIR / "configs")
        return cls.DEFAULT_SEED_FILE

    @classmethod
    def _seed_policies(cls, config_dir: Path) -> None:
        """
        Copy the shipped policies JSON into *config_dir* when it does not
        exist yet.
        """
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
            # intentional: packaged preset missing/unreadable — try the
            # filesystem fallback next.
            pass
        fallback = Path("resources/configs/rate_limiting-policies.json")
        if fallback.is_file():
            dest.write_text(fallback.read_text(encoding="utf-8"))

    # ---- Key-store kwargs / factory -----------------------------------------

    @staticmethod
    def _auth_redis_kwargs(args: Any) -> Dict[str, Any]:
        """
        Build redis kwargs for the auth key store (CLI args → env vars).
        """
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
            "redis_protocol": int(
                getattr(args, "auth_redis_protocol", 2)
                or os.environ.get("LLM_ROUTER_AUTH_REDIS_PROTOCOL", 2)
            ),
        }

    @staticmethod
    def _vault_kwargs() -> Dict[str, Any]:
        """
        Build vault kwargs for the auth key store from the standard
        ``LLM_ROUTER_AUTH_VAULT_*`` environment variables (same source the
        server engine uses — see ``core/engine.py``).
        """
        return {
            "addr": os.environ.get("LLM_ROUTER_AUTH_VAULT_ADDR", "").strip(),
            "mount_path": (
                os.environ.get("LLM_ROUTER_AUTH_VAULT_PATH", "").strip()
                or "secret/data/llm-router/api-keys"
            ),
            "auth_method": (
                os.environ.get("LLM_ROUTER_AUTH_VAULT_AUTH_METHOD", "kubernetes")
                .strip()
                .lower()
                or "kubernetes"
            ),
            "role_id": os.environ.get("LLM_ROUTER_AUTH_VAULT_ROLE_ID", "").strip(),
            "secret_id": os.environ.get(
                "LLM_ROUTER_AUTH_VAULT_SECRET_ID", ""
            ).strip(),
        }

    def _make_store(self, args: Any) -> Any:
        """
        Create the key store selected by ``--store``, forwarding the
        right kwargs (redis or vault) to the shared factory.
        """
        from llm_router_api.core.auth.key_store import create_key_store

        if args.store == "vault":
            kwargs = self._vault_kwargs()
            if not kwargs["addr"]:
                raise ValueError(
                    "LLM_ROUTER_AUTH_VAULT_ADDR is required for "
                    "--store vault (vault address, e.g. http://127.0.0.1:8200)"
                )
        else:
            kwargs = self._auth_redis_kwargs(args)
        store, _shared = create_key_store(store_type=args.store, **kwargs)
        return store

    # ---- Rate-limit preset loading -----------------------------------------

    @classmethod
    def _load_rate_limit_presets(cls) -> List[dict]:
        """
        Load predefined rate-limit presets
        (env var → user config → package resource → builtin).
        """
        env_path = os.environ.get("LLM_ROUTER_RATE_LIMITING_CONFIG", "").strip()

        def _try_load(path: Path) -> Optional[List[dict]]:
            if not path.exists():
                return None
            try:
                presets = json.loads(path.read_text(encoding="utf-8"))
                result = [p for p in presets if isinstance(p, dict) and "name" in p]
                return result if result else None
            except (json.JSONDecodeError, OSError):
                return None

        def _try_load_bytes(data: bytes) -> Optional[List[dict]]:
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
            # intentional: packaged preset missing/unreadable — fall back to
            # the builtin presets below.
            pass

        return cls._BUILTIN_RATE_LIMIT_PRESETS

    # ---- Subparser registration -------------------------------------------

    @classmethod
    def register_rate_limit_subparser(cls, parser: argparse.ArgumentParser) -> None:
        """
        Register the ``rate-limit`` sub-subcommands under *parser*.
        """
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
        parser: Union[argparse.ArgumentParser, argparse._SubParsersAction],
        nest_auth: bool = True,
    ) -> None:
        """
        Register the ``auth`` subparser with its child commands.
        """
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

        policy_parser = auth_sub.add_parser(cls.POLICY_NAME, help="Manage policies")
        policy_sub = policy_parser.add_subparsers(dest="policy_command")
        policy_sub.add_parser("list", help="List available policies")
        policy_create = policy_sub.add_parser("create", help="Create a new policy")
        policy_create.add_argument("name", help="Policy name")
        policy_create.add_argument("policy_json", help="JSON policy definition")
        cls._add_store_and_redis_args(policy_create)

        cls.register_rate_limit_subparser(auth_sub)

    # ---- Public entry points -----------------------------------------------

    @classmethod
    def build_parser(cls) -> argparse.ArgumentParser:
        """
        Build the standalone ``auth`` parser (single source of the tree).
        """
        parser = argparse.ArgumentParser(
            prog="llm-router auth",
            description="Manage API keys and authentication",
        )
        auth_sub = parser.add_subparsers(dest="auth_command")
        cls.register_parser(auth_sub, nest_auth=False)  # type: ignore[arg-type]
        return parser

    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """
        Dispatch an already-parsed *args* namespace (no re-parsing).
        """
        auth_command = getattr(args, "auth_command", None)
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
        return handler(args)

    @classmethod
    def run(cls, argv: Optional[List[str]] = None) -> int:
        """
        Standalone entry point: parse once, then dispatch on the namespace.
        """
        if argv is None:
            argv = sys.argv[1:]
        if not argv:
            cls.build_parser().print_help()
            return 0
        args = cls.build_parser().parse_args(argv)
        return cls.dispatch(args)

    # ---- Key handler commands (all private methods on the class) ----------

    def _handle_key(self, args: Any) -> int:
        """
        Route key subcommands via the dispatch table.
        """
        cmd = getattr(args, "key_command", None)
        if cmd is None:
            print(
                f"Usage: llm-router auth key <{'|'.join(self._KEY_COMMANDS)}>",
                file=sys.stderr,
            )
            return 1

        handler_method_name = self._KEY_COMMANDS.get(cmd)
        if handler_method_name is None:
            print(f"Unknown key command: {cmd}", file=sys.stderr)
            return 1
        return getattr(self, handler_method_name)(args)

    def _key_generate(self, args: Any) -> int:
        """
        Handle the 'generate' subcommand.
        """
        from llm_router_api.core.auth.key_generator import KeyGenerator
        from llm_router_api.core.auth.policies.builtin import get_builtin_policy

        policy = args.policy
        policy_obj = get_builtin_policy(policy)
        if policy_obj is None:
            print(f"Error: Policy '{policy}' does not exist.", file=sys.stderr)
            return 1

        expires: Optional[float]
        if args.expires in (None, ""):
            expires = None
        else:
            try:
                expires = float(args.expires)
            except ValueError:
                print(
                    f"Error: --expires must be a Unix timestamp "
                    f"(got '{args.expires}').",
                    file=sys.stderr,
                )
                return 1

        try:
            key_store = self._make_store(args)
            plaintext_key = asyncio.run(
                key_store.create_key(
                    {
                        "key_plain": KeyGenerator().generate(),
                        "policy_name": policy,
                        "expires_at": expires,
                        "metadata": {},
                    }
                )
            )
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if args.output:
            out_path = Path(args.output).expanduser()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(plaintext_key + "\n", encoding="utf-8")
            print(f"Generated key for policy '{policy}' written to {out_path}")
            print("⚠️  This key is displayed ONCE. Store it securely!")
        else:
            print(f"Generated key for policy '{policy}':")
            print(plaintext_key)
            print("\n⚠️  This key is displayed ONCE. Store it securely!")
        print(f"Expires at: {expires}")
        print(f"Policy: {policy}")
        return 0

    def _key_list(self, args: Any) -> int:
        """
        Handle the 'list' subcommand.
        """
        try:
            key_store = self._make_store(args)
            keys = asyncio.run(key_store.list_keys())
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if not keys:
            print("No API keys found.")
            return 0

        if getattr(args, "json", False):
            print(json.dumps(keys, indent=2))
            return 0

        max_w: Dict[str, int] = {
            "KEY_ID": 8,
            "PREFIX": 8,
            "POLICY": 8,
            "ACTIVE": 7,
            "EXPIRES": 10,
        }
        for k in keys:
            max_w["KEY_ID"] = max(max_w["KEY_ID"], len(k["key_id"]) + 1)
            max_w["PREFIX"] = max(max_w["PREFIX"], len(k.get("key_prefix", "")) + 1)
            max_w["POLICY"] = max(max_w["POLICY"], len(k.get("policy_name", "")) + 1)

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
                f"{k['key_id']:<{w[0]}} {k['key_prefix']:<{w[1]}} "
                f"{k['policy_name']:<{w[2]}} "
                f"{'yes' if k.get('is_active') else 'no':<{w[3]}} {exp_str:<{w[4]}}"
            )
            print(line)
        return 0

    def _key_action(self, key_store: Any, key_id: str, action: str) -> int:
        """
        Handle delete / disable / enable — they share the same flow.
        """
        method_name = f"{action}_key"
        success_msg = (
            f"Key {key_id} {'deleted' if action == 'delete' else action + 'd'}."
        )
        try:
            method = getattr(key_store, method_name)
            asyncio.run(method(key_id))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if hasattr(key_store, "_persist_seeds"):
            target = getattr(key_store, "_seed_file", None)
            if target:
                key_store._persist_seeds(target)

        print(success_msg)
        return 0

    def _key_mutate(self, args: Any, action: str) -> int:
        """
        Shared dispatcher for delete / disable / enable.
        """
        try:
            key_store = self._make_store(args)
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return self._key_action(key_store, args.key_id, action)

    def _key_mutate_delete(self, args: Any) -> int:
        """
        dispatch → _key_mutate with action='delete'.
        """
        return self._key_mutate(args, "delete")

    def _key_mutate_disable(self, args: Any) -> int:
        """
        dispatch → _key_mutate with action='disable'.
        """
        return self._key_mutate(args, "disable")

    def _key_mutate_enable(self, args: Any) -> int:
        """
        dispatch → _key_mutate with action='enable'.
        """
        return self._key_mutate(args, "enable")

    def _key_rotate(self, args: Any) -> int:
        """
        Handle the 'rotate' subcommand.
        """
        try:
            key_store = self._make_store(args)
            new_key = asyncio.run(key_store.rotate_key(args.key_id, args.grace))
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if hasattr(key_store, "_persist_seeds"):
            seed_file = getattr(key_store, "_seed_file", None)
            if seed_file:
                key_store._persist_seeds(seed_file)

        print(f"Rotated key {args.key_id} -> new key:")
        print(new_key)
        print("\n⚠️  This key is displayed ONCE. Store it securely!")
        return 0

    # ---- Policy handler ---------------------------------------------------

    def _handle_policy(self, args: Any) -> int:
        """
        Handle policy subcommands.
        """
        cmd = getattr(args, "policy_command", None)
        if cmd is None:
            print("Usage: llm-router auth policy <list|create> ...", file=sys.stderr)
            return 1

        if cmd == "list":
            from llm_router_api.core.auth.policies.builtin import (
                list_builtin_policies,
            )

            print("Builtin policies:")
            for name in list_builtin_policies():
                print(f"  {name}")
            return 0

        if cmd == "create":
            from llm_router_api.core.auth.policies.engine import EndpointPolicy
            from llm_router_api.core.auth.policies.builtin import register_policy

            try:
                policy_dict = json.loads(args.policy_json)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON: {e}", file=sys.stderr)
                return 1
            try:
                register_policy(args.name, EndpointPolicy(**policy_dict))
            except (TypeError, ValueError) as e:
                print(f"Error: Invalid policy definition: {e}", file=sys.stderr)
                return 1
            print(f"Policy '{args.name}' created.")
            return 0

        print(f"Unknown policy command: {cmd}", file=sys.stderr)
        return 1

    # ---- Rate-limit handler -----------------------------------------------

    def _handle_rate_limit(self, args: Any) -> int:
        """
        Handle rate-limit subcommands.
        """
        cmd = getattr(args, "rate_limit_command", None)
        if cmd is None:
            print(
                "Usage: llm-router auth rate-limit <list|apply|remove> ...",
                file=sys.stderr,
            )
            return 1
        handler = {
            "list": self._rl_list,
            "apply": self._rl_apply,
            "remove": self._rl_remove,
        }.get(cmd)
        if handler is None:
            print(f"Unknown rate-limit command: {cmd}", file=sys.stderr)
            return 1
        return handler(args)

    def _rl_list(self, args: Any) -> int:
        """
        List all available rate-limit presets.
        """
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

    def _resolve_rate_limit_preset(self, preset_name: str) -> Optional[int]:
        """
        Resolve a preset name to a per-minute rate limit (or ``None``).
        """
        presets = self._load_rate_limit_presets()
        preset = next((p for p in presets if p["name"] == preset_name), None)
        if not preset:
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
            print(
                f"Error: Unknown preset '{args.preset}'. Available: {names}",
                file=sys.stderr,
            )
            return 1

        try:
            key_store = self._make_store(args)
            asyncio.run(key_store.update_policy_override(args.key_id, rate_limit))
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print(
            f"Applied preset '{args.preset}' "
            f"(rate_limit='{rate_limit}'/min) to key {args.key_id}."
        )
        return 0

    def _rl_remove(self, args: Any) -> int:
        """
        Remove the rate-limit override from a key (any store backend).
        """
        try:
            key_store = self._make_store(args)
            asyncio.run(key_store.update_policy_override(args.key_id, None))
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print(
            f"Removed rate-limit override for key {args.key_id} "
            f"(will use global default)."
        )
        return 0
