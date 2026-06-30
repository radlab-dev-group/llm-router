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
import argparse
import asyncio

from pathlib import Path


# ---------------------------------------------------------------------------
# Shared argument helpers — avoid repeating the same --store / --auth-redis-*
# arguments on every subparser.
# ---------------------------------------------------------------------------

_STORE_CHOICES = ["memory", "redis", "vault"]

_KEY_ID_ARG = argparse.ArgumentDefaultsHelpFormatter, {
    "help": "Key ID to operate on"
}


def _add_store_and_redis_args(p: argparse.ArgumentParser) -> None:
    """Add ``--store`` and all ``--auth-redis-*`` flags to *p*.

    Called after ``p.add_argument("key_id", …)`` for key-manipulation
    subcommands, or standalone for commands that don't take a key ID.
    """
    p.add_argument(
        "--store",
        default="memory",
        choices=_STORE_CHOICES,
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


def _add_key_id_arg(p: argparse.ArgumentParser) -> None:
    """Add the positional ``key_id`` argument to *p*."""
    p.add_argument("key_id", help="Key ID to operate on")


# ---------------------------------------------------------------------------
# Seed file setup — shared between main() and _handle_key().
# ---------------------------------------------------------------------------

_SEED_DIR = Path.home() / ".llm-router"

# Default seed file path for memory key store — also used by constants.py and the shell script.
_DEFAULT_SEED_FILE = str(_SEED_DIR / "configs" / "auth" / "memory-keys.json")


def _ensure_seed_env() -> str:
    """Ensure seed directory structure and return the seed file path.

    Creates ``~/.llm-router/configs/auth/`` if missing.
    Seeds default rate-limiting-policies.json into ``configs/``.
    """
    _SEED_DIR.mkdir(exist_ok=True)

    auth_dir = _SEED_DIR / "configs" / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)

    # Seed default rate-limiting-policies.json if missing
    _seed_policies(_SEED_DIR / "configs")

    return _DEFAULT_SEED_FILE


def _seed_policies(config_dir: Path) -> None:
    """Copy the shipped policies JSON into *config_dir* when it does not exist yet."""
    dest = config_dir / "rate_limiting-policies.json"
    if dest.exists():
        return

    # Try to read from installed package resource (works after pip install)
    try:
        from importlib import resources as pkg_resources

        src_data = pkg_resources.files("llm_router_cli.resources.configs").joinpath(
            "rate_limiting-policies.json"
        ).read_bytes()
        dest.write_bytes(src_data)
        return
    except (ImportError, OSError):
        pass

    # Last resort: repo-relative path for development
    fallback = Path("resources/configs/rate_limiting-policies.json")
    if fallback.is_file():
        dest.write_text(fallback.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Redis kwargs helper (used by create_key_store calls).
# ---------------------------------------------------------------------------


def _auth_redis_kwargs(args) -> dict:
    """Build redis kwargs for auth key store.

    Priority: CLI args → env vars → defaults.
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
    }


def _extract_key_id(argv: list[str]) -> str | None:
    """Extract the positional key ID from argv (first non-flag token)."""
    for arg in argv:
        if not arg.startswith("-"):
            return arg
    return None


# ---------------------------------------------------------------------------
# Key command handler implementations — each handles ONE subcommand.
# ---------------------------------------------------------------------------


def _handle_key_generate(args, key_args) -> int:
    """Handle the 'generate' subcommand."""
    from llm_router_api.core.auth.key_generator import KeyGenerator
    from llm_router_api.core.auth.key_store import create_key_store
    from llm_router_api.core.auth.policies.builtin import get_builtin_policy

    gen = KeyGenerator()
    policy = "developer"
    expires = None
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
        store_type=args.store, **_auth_redis_kwargs(args)
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


def _handle_key_list(args, key_args) -> int:
    """Handle the 'list' subcommand."""
    from llm_router_api.core.auth.key_store import create_key_store

    key_store, _ = create_key_store(
        store_type=args.store, **_auth_redis_kwargs(args)
    )

    show_plain = getattr(args, "reveal", False)
    keys = asyncio.run(key_store.list_keys())
    if not keys:
        print("No API keys found.")
        return 0

    # Calculate column widths from data (dynamic, fits any key ID length)
    max_w = {"KEY_ID": 8, "PREFIX": 8, "POLICY": 8, "ACTIVE": 7, "EXPIRES": 10}
    for k in keys:
        exp_str = (
            f"{k.get('expires_at', 'none'):.0f}" if k.get("expires_at") else "none"
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

    hdr = f"{'KEY_ID':<{w[0]}} {'PREFIX':<{w[1]}} {'POLICY':<{w[2]}} {'ACTIVE':<{w[3]}} {'EXPIRES':<{w[4]}}"
    print(hdr)
    print("-" * len(hdr))

    for k in keys:
        exp_str = (
            f"{k.get('expires_at', 'none'):.0f}" if k.get("expires_at") else "none"
        )
        line = (
            f"{k['key_id']:<{w[0]}} "
            f"{k['key_prefix']:<{w[1]}} "
            f"{k['policy_name']:<{w[2]}} "
            f"{'yes' if k.get('is_active') else 'no':<{w[3]}} "
            f"{exp_str:<{w[4]}}"
        )
        if show_plain and "key_plain" in k:
            line += f"  PLAIN: {k['key_plain']}"
        print(line)
    return 0


def _handle_key_action(
    key_store, key_id: str, action: str, *, seed_file=None
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

    # Persist to seed file after mutations (only memory store has this attr).
    # For non-memory stores the key store writes directly, so seed_file is ignored.
    if hasattr(key_store, "_persist_seeds"):
        target = seed_file or getattr(key_store, "_seed_file", None)
        if target:
            key_store._persist_seeds(target)

    print(success_msg)
    return 0


def _handle_key_rotate(args, key_args) -> int:
    """Handle the 'rotate' subcommand."""
    from llm_router_api.core.auth.key_store import create_key_store

    key_id = _extract_key_id(key_args)
    if not key_id:
        print("Error: key_id is required for rotate.")
        return 1

    grace = 3600
    for i, arg in enumerate(key_args):
        if arg == "--grace" and i + 1 < len(key_args):
            grace = int(key_args[i + 1])

    key_store, _ = create_key_store(
        store_type=args.store, **_auth_redis_kwargs(args)
    )
    seed_file = getattr(key_store, "_seed_file", None)

    new_key = asyncio.run(key_store.rotate_key(key_id, grace))
    if hasattr(key_store, "_persist_seeds") and seed_file:
        key_store._persist_seeds(seed_file)

    print(f"Rotated key {key_id} -> new key:")
    print(new_key)
    print("\n⚠️  This key is displayed ONCE. Store it securely!")
    return 0


def _handle_key_reveal(args, key_args) -> int:
    """Handle the 'reveal' subcommand."""
    key_id = _extract_key_id(key_args)
    if not key_id:
        print("Error: key_id is required for reveal.")
        return 1

    key_store, _ = create_key_store(
        store_type=args.store, **_auth_redis_kwargs(args)
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


# ---------------------------------------------------------------------------
# Dispatcher mapping command name → handler function.
# Handlers receive (args, key_args).  Key-manipulation commands extract
# the positional ID themselves; other commands receive full argv for parsing.
# ---------------------------------------------------------------------------

_KEY_COMMANDS = {
    "generate": _handle_key_generate,
    "list": _handle_key_list,
    "delete": lambda a, k: _key_mutate(a, k, "delete"),
    "disable": lambda a, k: _key_mutate(a, k, "disable"),
    "enable": lambda a, k: _key_mutate(a, k, "enable"),
    "rotate": _handle_key_rotate,
    "reveal": _handle_key_reveal,
}


def _key_mutate(args, key_args: list[str], action: str) -> int:
    """Shared dispatcher for delete / disable / enable."""
    key_id = _extract_key_id(key_args)
    if not key_id:
        print(f"Error: key_id is required for {action}.")
        return 1

    key_store, _ = create_key_store(
        store_type=args.store, **_auth_redis_kwargs(args)
    )
    seed_file = getattr(key_store, "_seed_file", None)
    return _handle_key_action(key_store, key_id, action, seed_file=seed_file)


# ---------------------------------------------------------------------------
# Preset loading — searches user config dir, then installed package, then built-in.
# ---------------------------------------------------------------------------

_RATE_LIMITING_CONFIG_FILE = os.environ.get(
    "LLM_ROUTER_RATE_LIMITING_CONFIG", ""
).strip()


def _load_rate_limit_presets() -> list[dict]:
    """Load predefined rate-limit presets from the JSON config file.

    Search order::

        1. ``$LLM_ROUTER_RATE_LIMITING_CONFIG`` (absolute path to file or directory)
        2. ``~/.llm-router/configs/rate_limiting-policies.json`` (user config dir)
        3. Package resource ``llm_router_cli.resources.configs`` (installed via pip)
        4. Minimal built-in presets (last resort)
    """
    _BUILTIN_FALLBACK = [
        {"name": "free", "rpm": 10, "description": "Free tier — limited usage"},
        {"name": "basic", "rpm": 60, "description": "Standard (1/s)"},
        {"name": "pro", "rpm": 120, "description": "Pro tier (2/s)"},
        {"name": "enterprise", "rpm": 500, "description": "High throughput"},
    ]

    def _try_load(path: Path) -> list[dict] | None:
        if not path.exists():
            return None
        try:
            presets = json.loads(path.read_text(encoding="utf-8"))
            result = [p for p in presets if isinstance(p, dict) and "name" in p]
            if result:
                return result
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _try_load_bytes(data: bytes) -> list[dict] | None:
        try:
            presets = json.loads(data)
            result = [p for p in presets if isinstance(p, dict) and "name" in p]
            if result:
                return result
        except (json.JSONDecodeError, OSError):
            pass
        return None

    # 1. User-provided absolute path (file or directory)
    if _RATE_LIMITING_CONFIG_FILE:
        candidate = Path(_RATE_LIMITING_CONFIG_FILE)
        loaded = _try_load(candidate)
        if loaded is not None:
            return loaded
        # Maybe it's a directory — append the expected filename
        loaded = _try_load(candidate / "rate_limiting-policies.json")
        if loaded is not None:
            return loaded

    # 2. User config dir (default installed location)
    user_config = Path.home() / ".llm-router" / "configs" / "rate_limiting-policies.json"
    loaded = _try_load(user_config)
    if loaded is not None:
        return loaded

    # 3. Installed package resource (works after pip install, no cwd dependency)
    try:
        from importlib import resources as pkg_resources

        _PACKAGE_RES = pkg_resources.files("llm_router_cli.resources.configs") / "rate_limiting-policies.json"
        if hasattr(_PACKAGE_RES, "read_bytes"):  # Python 3.9+
            loaded = _try_load_bytes(_PACKAGE_RES.read_bytes())
        elif hasattr(_PACKAGE_RES, "joinpath"):  # fallback for older Python
            loaded = _try_load(Path(_PACKAGE_RES))
        if loaded is not None:
            return loaded
    except (ImportError, OSError):
        pass

    # 4. Built-in fallback
    return _BUILTIN_FALLBACK


# ---------------------------------------------------------------------------
# Subparser registration for rate-limit subcommand.
# ---------------------------------------------------------------------------


def register_rate_limit_subparser(parser: argparse.ArgumentParser) -> None:
    """Register the ``rate-limit`` sub-subcommands under *parser* (the auth subparsers)."""
    rl_parser = parser.add_parser(
        "rate-limit",
        help="Manage rate limiting presets and per-key overrides",
    )
    rl_sub = rl_parser.add_subparsers(dest="rate_limit_command")

    # -- list --
    rl_list = rl_sub.add_parser(
        "list",
        help="List available rate-limit presets",
    )

    # -- apply <key_id> --preset <name> --
    rl_apply = rl_sub.add_parser(
        "apply",
        help="Apply a rate-limit preset to an existing key",
    )
    _add_key_id_arg(rl_apply)
    rl_apply.add_argument("--preset", required=True, help="Preset name")
    rl_apply.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend (default: memory)",
    )
    rl_apply.add_argument("--auth-redis-host", default=None, help="Redis host for auth key store")
    rl_apply.add_argument("--auth-redis-port", type=int, default=None, help="Redis port for auth key store")
    rl_apply.add_argument("--auth-redis-db", type=int, default=None, help="Redis database for auth key store")
    rl_apply.add_argument("--auth-redis-password", default=None, help="Redis password for auth key store")

    # -- remove <key_id> --
    rl_remove = rl_sub.add_parser(
        "remove",
        help="Remove rate-limit override from a key (revert to global default)",
    )
    _add_key_id_arg(rl_remove)
    rl_remove.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend (default: memory)",
    )
    rl_remove.add_argument("--auth-redis-host", default=None, help="Redis host for auth key store")
    rl_remove.add_argument("--auth-redis-port", type=int, default=None, help="Redis port for auth key store")
    rl_remove.add_argument("--auth-redis-db", type=int, default=None, help="Redis database for auth key store")
    rl_remove.add_argument("--auth-redis-password", default=None, help="Redis password for auth key store")


def register_auth_subparser(
    parser: argparse.ArgumentParser, nest_auth: bool = True
) -> None:
    """Register the ``auth`` subparser with its child commands.

    Parameters
    ----------
    parser : argparse.ArgumentParser
        The parent argument parser (or subparsers action) to register under.
    nest_auth : bool
        If True (default), wrap key/policy under an intermediate ``"auth"``
        subcommand (for use inside ``_auth_main`` which builds its own top-level
        parser).  When False, register key/policy directly under the supplied
        ``parser`` (for the top-level CLI in ``__init__.py``).
    """
    if nest_auth:
        auth_parser = parser.add_parser(
            "auth",
            help="Manage API keys and authentication",
        )
        auth_sub = auth_parser.add_subparsers(dest="auth_command")
    else:
        auth_sub = parser

    # -- key subparser --------------------
    key_parser = auth_sub.add_parser(
        "key",
        help="Manage API keys",
    )
    key_sub = key_parser.add_subparsers(dest="key_command")

    # -- generate --
    key_generate = key_sub.add_parser(
        "generate",
        help="Generate a new API key",
    )
    _add_store_and_redis_args(key_generate)
    key_generate.add_argument(
        "--policy",
        default="developer",
        help="Policy name to assign to the new key",
    )
    key_generate.add_argument(
        "--expires",
        type=str,
        default=None,
        help="Expiry time (Unix timestamp or None for no expiry)",
    )
    key_generate.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )

    # -- list --
    key_list = key_sub.add_parser(
        "list",
        help="List all API keys",
    )
    _add_store_and_redis_args(key_list)
    key_list.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output in JSON format",
    )
    key_list.add_argument(
        "--reveal",
        action="store_true",
        default=False,
        help="Reveal plaintext keys (memory store only)",
    )

    # -- delete / disable / enable -- (key_id + shared args)
    for name, help_text in [
        ("delete", "Delete an API key"),
        ("disable", "Disable an API key (deactivate without deleting)"),
        ("enable", "Re-enable a previously disabled API key"),
    ]:
        sub = key_sub.add_parser(name, help=help_text)
        _add_key_id_arg(sub)
        _add_store_and_redis_args(sub)

    # -- rotate -- (key_id + shared args + extra)
    key_rotate = key_sub.add_parser(
        "rotate",
        help="Rotate an API key",
    )
    _add_key_id_arg(key_rotate)
    _add_store_and_redis_args(key_rotate)
    key_rotate.add_argument(
        "--grace",
        type=int,
        default=3600,
        help="Grace period in seconds (default: 3600)",
    )

    # -- reveal -- (key_id + shared args)
    key_reveal = key_sub.add_parser(
        "reveal",
        help="Reveal a key (only available in memory store)",
    )
    _add_key_id_arg(key_reveal)
    _add_store_and_redis_args(key_reveal)

    # -- policy subparser --------------------
    policy_parser = auth_sub.add_parser(
        "policy",
        help="Manage policies",
    )
    policy_sub = policy_parser.add_subparsers(dest="policy_command")

    policy_list = policy_sub.add_parser(
        "list",
        help="List available policies",
    )

    policy_create = policy_sub.add_parser(
        "create",
        help="Create a new policy",
    )
    policy_create.add_argument(
        "name",
        help="Policy name",
    )
    policy_create.add_argument(
        "policy_json",
        help="JSON policy definition",
    )
    _add_store_and_redis_args(policy_create)

    # -- rate-limit subparser --------------------
    register_rate_limit_subparser(auth_sub)


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point for auth CLI commands.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments. Defaults to ``sys.argv``.

    Returns
    -------
    int
        Exit code.
    """
    from llm_router_api.core.auth.key_store import create_key_store

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description="Manage API keys and authentication"
    )
    auth_sub = parser.add_subparsers(dest="auth_command")
    # Top-level --store for key store backend. Subcommands override this.
    parser.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend (default: memory)",
    )

    register_auth_subparser(auth_sub, nest_auth=False)
    args = parser.parse_args(argv)

    if args.auth_command is None or not argv:
        parser.print_help()
        return 0

    cmd = argv[0]
    sub = argv[1:] if len(argv) > 1 else []
    seed_file = _ensure_seed_env()

    if cmd == "key":
        return _handle_key(args, sub, seed_file)
    elif cmd == "policy":
        return _handle_policy(args, sub)
    elif cmd == "rate-limit":
        return _handle_rate_limit(sub)
    else:
        parser.print_help()
        return 1


def _handle_key(args, sub: list, seed_file: str) -> int:
    """Route key subcommands via the COMMANDS dispatch table."""
    from llm_router_api.core.auth.key_store import create_key_store

    if not sub:
        print(
            "Usage: llm-router auth key <generate|list|delete|disable|enable|rotate|reveal>"
        )
        return 1

    cmd = sub[0]
    key_args = sub[1:]

    handler = _KEY_COMMANDS.get(cmd)
    if handler is None:
        print(f"Unknown key command: {cmd}")
        return 1

    # Handlers that don't take (args, key_args) — special-cased via lambda
    if cmd in ("delete", "disable", "enable"):
        key_id = _extract_key_id(key_args)
        if not key_id:
            print(f"Error: key_id is required for {cmd}.")
            return 1

        key_store, _ = create_key_store(
            store_type=getattr(args, "store", "memory"),
            **_auth_redis_kwargs(args),
        )
        return _handle_key_action(key_store, key_id, cmd, seed_file=seed_file)

    # All other handlers receive (args, key_args) — they create their own store
    return handler(args, key_args)


def _handle_policy(args, sub: list) -> int:
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

    elif cmd == "create":
        if len(sub) < 3:
            print("Usage: llm-router auth policy create <name> <json-policy>")
            return 1

        name = sub[1]
        policy_json = sub[2]

        try:
            policy_dict = json.loads(policy_json)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON: {e}")
            return 1

        policy = EndpointPolicy(**policy_dict)
        register_policy(name, policy)
        print(f"Policy '{name}' created.")
        return 0

    else:
        print(f"Unknown policy command: {cmd}")
        return 1


# ---------------------------------------------------------------------------
# Rate-limit handler.
# ---------------------------------------------------------------------------

_RATE_LIMIT_COMMANDS = {
    "list": lambda sub: _rl_list(sub),
    "apply": lambda sub: _rl_apply(sub),
    "remove": lambda sub: _rl_remove(sub),
}


def _handle_rate_limit(sub: list[str]) -> int:
    """Handle rate-limit subcommands."""
    if not sub:
        print("Usage: llm-router auth rate-limit <list|apply|remove> ...")
        return 1

    cmd = sub[0]
    handler = _RATE_LIMIT_COMMANDS.get(cmd)
    if handler is None:
        print(f"Unknown rate-limit command: {cmd}")
        return 1
    return handler(sub)


def _rl_list(sub: list[str]) -> int:
    """List all available rate-limit presets."""
    presets = _load_rate_limit_presets()
    if not presets:
        print("No presets found.")
        return 1

    # Calculate column widths
    max_name = max(len(p["name"]) for p in presets)
    max_rpm = max(len(str(p.get("rpm", "-"))) for p in presets)

    print("Available rate-limit presets:")
    print(f"  {'NAME':<{max_name}}  {'RPM':>{max_rpm}}  DESCRIPTION")
    print(f"  {'-' * max_name}  {'-' * max_rpm}  {'-----------'}")
    for p in presets:
        rpm = str(p.get("rpm", "-")) if p.get("rpm") else f"{p.get('daily_limit', 'N/A')}/day"
        print(f"  {p['name']:<{max_name}}  {rpm:>{max_rpm}}  {p['description']}")
    return 0


def _rl_apply(sub: list[str]) -> int:
    """Apply a rate-limit preset to an existing key."""
    if len(sub) < 2:
        print("Usage: llm-router auth rate-limit apply <key_id> --preset <name>")
        return 1

    key_id = sub[1]
    store = "memory"
    preset_name = None
    redis_kwargs = {}

    for i, arg in enumerate(sub):
        if arg == "--store" and i + 1 < len(sub):
            store = sub[i + 1]
        elif arg == "--preset" and i + 1 < len(sub):
            preset_name = sub[i + 1]
        elif arg == "--auth-redis-host" and i + 1 < len(sub):
            redis_kwargs["host"] = sub[i + 1]
        elif arg == "--auth-redis-port" and i + 1 < len(sub):
            redis_kwargs["port"] = int(sub[i + 1])
        elif arg == "--auth-redis-db" and i + 1 < len(sub):
            redis_kwargs["db"] = int(sub[i + 1])
        elif arg == "--auth-redis-password" and i + 1 < len(sub):
            redis_kwargs["password"] = sub[i + 1]

    if not preset_name:
        print("Error: --preset is required.")
        return 1

    presets = _load_rate_limit_presets()
    preset = next((p for p in presets if p["name"] == preset_name), None)
    if not preset:
        names = ", ".join(p["name"] for p in presets)
        print(f"Error: Unknown preset '{preset_name}'. Available: {names}")
        return 1

    rate_limit = preset.get("rpm")
    daily_limit = preset.get("daily_limit")
    if rate_limit is None and daily_limit is not None:
        # Convert daily to per-minute approximation
        rate_limit = max(1, daily_limit // 1440)

    # Apply based on store type
    from pathlib import Path as _Path
    seed_file = _DEFAULT_SEED_FILE
    seed_path = _Path(seed_file)

    if store == "memory":
        # Edit seed file directly
        if not seed_path.exists():
            print(f"Error: Seed file {seed_file} does not exist. Generate keys first.")
            return 1

        keys = json.loads(seed_path.read_text(encoding="utf-8"))
        if not isinstance(keys, list):
            print(f"Error: Seed file must contain a JSON array.")
            return 1

        found = False
        for rec in keys:
            if rec.get("key_id") == key_id or rec.get("key_plain", "").startswith(key_id[:7]):
                override = rec.get("policy_override") or {}
                override["rate_limit"] = rate_limit
                rec["policy_override"] = override
                found = True
                break

        if not found:
            print(f"Error: Key '{key_id}' not found in seed file.")
            return 1

        seed_path.write_text(json.dumps(keys, indent=2) + "\n", encoding="utf-8")
        print(f"Applied preset '{preset_name}' (rate_limit={rate_limit}/min) to key {key_id}.")

    elif store == "redis":
        import redis as _redis_mod

        host = redis_kwargs.get("host") or os.environ.get("LLM_ROUTER_AUTH_REDIS_HOST", "127.0.0.1")
        port = int(redis_kwargs.get("port") or os.environ.get("LLM_ROUTER_AUTH_REDIS_PORT", 6379))
        db = int(redis_kwargs.get("db") or os.environ.get("LLM_ROUTER_AUTH_REDIS_DB", 0))
        password = redis_kwargs.get("password") or os.environ.get("LLM_ROUTER_AUTH_REDIS_PASSWORD")

        r = _redis_mod.Redis(host=host, port=port, db=db, decode_responses=True, password=password)
        key_hash_key = f"auth:key:{key_id}"
        raw = r.hget(key_hash_key, "policy_override")
        policy_override = json.loads(raw) if raw else {}
        policy_override["rate_limit"] = rate_limit
        r.hset(key_hash_key, "policy_override", json.dumps(policy_override))
        print(f"Applied preset '{preset_name}' (rate_limit={rate_limit}/min) to key {key_id}.")

    elif store == "vault":
        print("Error: 'rate-limit apply' on vault store requires Vault API. Use seed file or --store memory.")
        return 1

    else:
        print(f"Error: Unknown store '{store}'.")
        return 1

    return 0


def _rl_remove(sub: list[str]) -> int:
    """Remove rate-limit override from a key."""
    if len(sub) < 2:
        print("Usage: llm-router auth rate-limit remove <key_id>")
        return 1

    key_id = sub[1]
    store = "memory"

    for i, arg in enumerate(sub):
        if arg == "--store" and i + 1 < len(sub):
            store = sub[i + 1]

    from pathlib import Path as _Path
    seed_file = _DEFAULT_SEED_FILE
    seed_path = _Path(seed_file)

    if store == "memory":
        if not seed_path.exists():
            print(f"Error: Seed file {seed_file} does not exist.")
            return 1

        keys = json.loads(seed_path.read_text(encoding="utf-8"))
        if not isinstance(keys, list):
            print(f"Error: Seed file must contain a JSON array.")
            return 1

        found = False
        for rec in keys:
            if rec.get("key_id") == key_id or rec.get("key_plain", "").startswith(key_id[:7]):
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

        seed_path.write_text(json.dumps(keys, indent=2) + "\n", encoding="utf-8")
        print(f"Removed rate-limit override for key {key_id} (will use global default).")

    elif store == "redis":
        import redis as _redis_mod

        host = os.environ.get("LLM_ROUTER_AUTH_REDIS_HOST", "127.0.0.1")
        port = int(os.environ.get("LLM_ROUTER_AUTH_REDIS_PORT", 6379))
        db = int(os.environ.get("LLM_ROUTER_AUTH_REDIS_DB", 0))
        password = os.environ.get("LLM_ROUTER_AUTH_REDIS_PASSWORD")

        r = _redis_mod.Redis(host=host, port=port, db=db, decode_responses=True, password=password)
        key_hash_key = f"auth:key:{key_id}"
        raw = r.hget(key_hash_key, "policy_override")
        policy_override = json.loads(raw) if raw else {}
        if "rate_limit" in policy_override:
            del policy_override["rate_limit"]
        if not policy_override:
            r.hdel(key_hash_key, "policy_override")
        else:
            r.hset(key_hash_key, "policy_override", json.dumps(policy_override))
        print(f"Removed rate-limit override for key {key_id} (will use global default).")

    elif store == "vault":
        print("Error: 'rate-limit remove' on vault store requires Vault API. Use seed file or --store memory.")
        return 1

    else:
        print(f"Error: Unknown store '{store}'.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
