"""
CLI commands for API key management.

Usage::

    llm-router auth key generate [--policy developer] [--store memory]
    llm-router auth key list [--store memory]
    llm-router auth key delete <key-id> [--store memory]
    llm-router auth key rotate <key-id> [--grace 3600]
    llm-router auth key reveal <key-id>
    llm-router auth policy list
    llm-router auth policy create <name> <json-policy>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


def register_auth_subparser(parser: argparse.ArgumentParser, nest_auth: bool = True) -> None:
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

    key_generate = key_sub.add_parser(
        "generate",
        help="Generate a new API key",
    )
    key_generate.add_argument(
        "--policy",
        default="developer",
        help="Policy name to assign to the new key",
    )
    key_generate.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend",
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

    key_list = key_sub.add_parser(
        "list",
        help="List all API keys",
    )
    key_list.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend",
    )
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

    key_delete = key_sub.add_parser(
        "delete",
        help="Delete an API key",
    )
    key_delete.add_argument(
        "key_id",
        help="Key ID to delete",
    )
    key_delete.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend",
    )

    key_rotate = key_sub.add_parser(
        "rotate",
        help="Rotate an API key",
    )
    key_rotate.add_argument(
        "key_id",
        help="Key ID to rotate",
    )
    key_rotate.add_argument(
        "--grace",
        type=int,
        default=3600,
        help="Grace period in seconds (default: 3600)",
    )
    key_rotate.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend",
    )

    key_reveal = key_sub.add_parser(
        "reveal",
        help="Reveal a key (only available in memory store)",
    )
    key_reveal.add_argument(
        "key_id",
        help="Key ID to reveal",
    )
    key_reveal.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend",
    )

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
    policy_create.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend",
    )


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
    from llm_router_api.core.auth.key_generator import KeyGenerator
    from llm_router_api.core.auth.key_store import create_key_store
    from llm_router_api.core.auth.policies.engine import PermissionEngine
    from llm_router_api.core.auth.policies.builtin import list_builtin_policies, register_policy

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Manage API keys and authentication")
    auth_sub = parser.add_subparsers(dest="auth_command")
    # Top-level --store for key store backend. Subcommands override this.
    parser.add_argument(
        "--store",
        default="memory",
        choices=["memory", "redis", "vault"],
        help="Key store backend (default: memory)",
    )

    # nest_auth=False because _auth_main already has its own top-level parser.
    # Only the TOP-LEVEL CLI (in __init__.py) should add an "auth" wrapper.
    register_auth_subparser(auth_sub, nest_auth=False)

    args = parser.parse_args(argv)

    if args.auth_command is None:
        parser.print_help()
        return 0
    if not argv:
        parser.print_help()
        return 0

    cmd = argv[0]
    sub = argv[1:] if len(argv) > 1 else []

    # Default seed file for memory store so keys survive across CLI invocations.
    seed_dir = Path.home() / ".llm-router"
    seed_dir.mkdir(exist_ok=True)
    seed_file = str(seed_dir / "keys.json")

    os.environ["LLM_ROUTER_AUTH_MEMORY_SEED_FILE"] = seed_file

    key_store = create_key_store(
        store_type=args.store,
        redis_host=getattr(args, "auth_addr", None),
        redis_port=getattr(args, "auth_port", 6379),
        redis_db=getattr(args, "auth_db", 0),
        redis_password=getattr(args, "auth_password", None),
    )

    if cmd == "key":
        return _handle_key(args, sub)
    elif cmd == "policy":
        return _handle_policy(args, sub)
    else:
        parser.print_help()
        return 1


def _handle_key(args, sub: list) -> int:
    """Handle key subcommands."""
    import asyncio
    from llm_router_api.core.auth.key_generator import KeyGenerator
    from llm_router_api.core.auth.key_store import create_key_store
    from llm_router_api.core.auth.policies.builtin import get_builtin_policy

    if not sub:
        print("Usage: llm-router auth key <generate|list|delete|rotate|reveal>")
        return 1

    cmd = sub[0]
    key_args = sub[1:]

    key_store = create_key_store(
        store_type=getattr(args, "store", "memory"),
        redis_host=getattr(args, "auth_addr", None),
        redis_port=getattr(args, "auth_port", 6379),
        redis_db=getattr(args, "auth_db", 0),
        redis_password=getattr(args, "auth_password", None),
    )

    async def _run():
        seed_file = getattr(key_store, "_seed_file", None)

        if cmd == "generate":
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

            record = {
                "key_plain": gen.generate(),
                "policy_name": policy,
                "expires_at": expires,
                "metadata": {},
            }
            plaintext_key = await key_store.create_key(record)

            print(f"Generated key for policy '{policy}':")
            print(plaintext_key)
            print("\n⚠️  This key is displayed ONCE. Store it securely!")
            print(f"Expires at: {expires}")
            print(f"Policy: {policy}")
            return 0

        elif cmd == "list":
            show_plain = getattr(args, "reveal", False)
            keys = await key_store.list_keys()
            if not keys:
                print("No API keys found.")
                return 0

            print(f"{'KEY_ID':<20} {'PREFIX':<10} {'POLICY':<15} {'ACTIVE':<8} {'EXPIRES':<20}")
            print("-" * 75)
            for k in keys:
                expires_str = (
                    f"{k.get('expires_at', 'none'):.0f}" if k.get('expires_at') else "none"
                )
                line = (
                    f"{k['key_id']:<20} {k['key_prefix']:<10} {k['policy_name']:<15} "
                    f"{'yes' if k.get('is_active') else 'no':<8} {expires_str:<20}"
                )
                if show_plain and "key_plain" in k:
                    line += f"  PLAIN: {k['key_plain']}"
                print(line)
            return 0

        elif cmd == "delete":
            key_id = key_args[0] if key_args else None
            if not key_id:
                print("Error: key_id is required for delete.")
                return 1
            await key_store.delete_key(key_id)
            if seed_file:
                key_store._persist_seeds(seed_file)
            print(f"Key {key_id} deleted.")
            return 0

        elif cmd == "rotate":
            key_id = key_args[0] if key_args else None
            grace = 3600
            for i, arg in enumerate(key_args):
                if arg == "--grace" and i + 1 < len(key_args):
                    grace = int(key_args[i + 1])

            if not key_id:
                print("Error: key_id is required for rotate.")
                return 1

            new_key = await key_store.rotate_key(key_id, grace)
            if seed_file:
                key_store._persist_seeds(seed_file)
            print(f"Rotated key {key_id} -> new key:")
            print(new_key)
            print("\n⚠️  This key is displayed ONCE. Store it securely!")
            return 0

        elif cmd == "reveal":
            key_id = key_args[0] if key_args else None
            if not key_id:
                print("Error: key_id is required for reveal.")
                return 1

            record = await key_store.get_key_by_id(key_id)
            if not record:
                print(f"Key {key_id} not found.")
                return 1

            # Show plaintext key if available (only in memory store)
            plain = record.get("key_plain")
            if plain:
                print(f"Key {key_id}:")
                print(plain)
            else:
                print(f"Key {key_id} hash: {record.get('key_hash', 'N/A')}")
            return 0

        else:
            print(f"Unknown key command: {cmd}")
            return 1

    return asyncio.run(_run())


def _handle_policy(args, sub: list) -> int:
    """Handle policy subcommands."""
    from llm_router_api.core.auth.policies.engine import EndpointPolicy
    from llm_router_api.core.auth.policies.builtin import list_builtin_policies, register_policy

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


if __name__ == "__main__":
    sys.exit(main())
