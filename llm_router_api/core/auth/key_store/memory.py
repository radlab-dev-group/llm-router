"""
In-memory key store — suitable for development and testing only.
Keys are lost on restart.

Seed file
---------
When ``seed_file`` is passed to the constructor, the store loads key
records from a JSON file at startup.  This is the only way to supply
API keys when the router runs as a separate process from the CLI.

Seed file format
~~~~~~~~~~~~~~~~
::

    [
      { "key_plain": "sk-litm-...", "policy_name": "developer" },
      { "key_plain": "sk-litm-...", "policy_name": "readonly", "expires_at": 1700000000 },
    ]

Env var ``LLM_ROUTER_AUTH_MEMORY_SEED_FILE`` controls the path
(default ``~/.llm-router/keys.json``).
"""

from __future__ import annotations

import json
import time
import uuid
import bcrypt
import asyncio
import logging as _logging

from pathlib import Path

from llm_router_api.core.auth.key_store.interface import KeyStoreInterface


class MemoryKeyStore(KeyStoreInterface):
    """In-memory store for development / testing."""

    def __init__(self, seed_file: str | None = None) -> None:
        self._keys: dict[str, dict] = {}
        self._by_hash: dict[str, str] = {}  # hash → key_id
        self._seed_file = seed_file
        if seed_file:
            self._seed_keys(seed_file)

    # -- seed loading ------------------------------
    @staticmethod
    def _load_seeds(seed_file: str) -> list[dict]:
        """Load key seed records from a JSON file."""
        path = Path(seed_file).expanduser()
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        records = json.loads(raw)
        if not isinstance(records, list):
            raise ValueError(
                f"Seed file {seed_file} must contain a JSON array, "
                f"got {type(records).__name__}"
            )
        for rec in records:
            if "key_plain" not in rec:
                raise ValueError(f"Seed record missing 'key_plain': {rec}")
        return records

    def _seed_keys(self, seed_file: str) -> None:
        """Load seed records into the key store."""
        for rec in self._load_seeds(seed_file):
            rec = dict(rec)  # prevent mutating the loaded JSON dict
            key_plain: str = rec.pop("key_plain")
            key_hash = bcrypt.hashpw(key_plain.encode(), bcrypt.gensalt()).decode()
            key_id = rec.get("key_id", f"seed-{uuid.uuid4().hex[:8]}")
            now = rec.get("created_at", time.time())
            is_active = rec.get("is_active", True)
            api_record = {
                "key_id": key_id,
                "key_hash": key_hash,
                "key_plain": key_plain,
                "key_prefix": key_plain[:7] if len(key_plain) > 6 else key_plain,
                "policy_name": rec.get("policy_name", "developer"),
                "policy_override": rec.get("policy_override"),
                "created_at": now,
                "expires_at": rec.get("expires_at"),
                "last_used_at": rec.get("last_used_at"),
                "is_active": is_active,
                "rotate_at": None,
                "grace_until": None,
                "metadata": rec.get("metadata", {}),
            }
            self._keys[key_id] = api_record
            self._by_hash[key_hash] = key_id

    def _persist_seeds(self, seed_file: str) -> None:
        """Write all current keys back to the seed file.

        All records are persisted with their current ``is_active`` state —
        deleted keys (popped from ``_keys``) are dropped; disabled keys
        (``is_active=False``) survive so that ``enable`` works after a restart.
        """
        path = Path(seed_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        out: list[dict] = [
            {
                "key_plain": rec.get("key_plain", ""),
                "key_id": rec["key_id"],
                "policy_name": rec["policy_name"],
                "is_active": rec.get("is_active", True),
                "expires_at": rec.get("expires_at"),
                "created_at": rec.get("created_at"),
                "metadata": rec.get("metadata", {}),
            }
            for rec in self._keys.values()
        ]
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    # -- sync helpers ----------------------------------------------
    @staticmethod
    def _run_async(coro):
        """Run an async coroutine from a synchronous context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop:
            return asyncio.run_coroutine_threadsafe(coro, loop).result()
        return asyncio.run(coro)

    # -- lookups ----------------------------------------------------------------
    async def get_key_by_hash(self, key_hash: str) -> dict | None:
        key_id = self._by_hash.get(key_hash)
        if key_id is None:
            return None
        record = self._keys.get(key_id)
        if record and not record.get("is_active"):
            return None
        return record

    def get_key_by_hash_sync(self, key_hash: str) -> dict | None:
        return self._run_async(self.get_key_by_hash(key_hash))

    async def get_key_by_id(self, key_id: str) -> dict | None:
        record = self._keys.get(key_id)
        if record and not record.get("is_active"):
            return None
        return record

    async def get_key_by_plain(self, key_plain: str) -> dict | None:
        """Look up a key record by its **plaintext** key."""
        logger = _logging.getLogger(__name__)
        prefix = key_plain[:7] if len(key_plain) > 6 else key_plain
        for rec_id, record in self._keys.items():
            stored = record.get("key_prefix", "")
            if stored == prefix:
                logger.debug(
                    "get_key_by_plain: candidate prefix=%s (id=%s) — full match check pending",
                    prefix,
                    rec_id[:8],
                )
                if record.get("key_plain") == key_plain:
                    logger.info(
                        "get_key_by_plain: MATCH prefix=%s (id=%s)",
                        prefix,
                        rec_id[:8],
                    )
                    return record
        logger.warning(
            "get_key_by_plain: NO MATCH for key with prefix=%s (total keys=%d)",
            prefix,
            len(self._keys),
        )
        return None

    def get_key_by_plain_sync(self, key_plain: str) -> dict | None:
        """Synchronous version of :meth:`get_key_by_plain`."""
        prefix = key_plain[:7] if len(key_plain) > 6 else key_plain
        logger = _logging.getLogger(__name__)
        logger.debug(
            "get_key_by_plain_sync: checking prefix=%s (total_keys=%d)",
            prefix,
            len(self._keys),
        )
        return self._run_async(self.get_key_by_plain(key_plain))

    # -- mutations --------------------------------------------------------------
    async def create_key(self, record: dict) -> str:
        record = dict(record)  # prevent mutating caller's dict
        key_plain: str = record.pop("key_plain")
        key_hash = bcrypt.hashpw(key_plain.encode(), bcrypt.gensalt()).decode()

        key_id = f"dev-{uuid.uuid4().hex[:8]}"
        now = time.time()
        api_record = {
            "key_id": key_id,
            "key_hash": key_hash,
            "key_plain": key_plain,  # keep plaintext for seed file
            "key_prefix": key_plain[:7] if len(key_plain) > 6 else key_plain,
            "policy_name": record.get("policy_name", "developer"),
            "policy_override": record.get("policy_override"),
            "created_at": now,
            "expires_at": record.get("expires_at"),
            "last_used_at": None,
            "is_active": True,
            "rotate_at": None,
            "grace_until": None,
            "metadata": record.get("metadata", {}),
        }
        self._keys[key_id] = api_record
        self._by_hash[key_hash] = key_id
        # Persist to seed file if one is configured
        if self._seed_file:
            self._persist_seeds(self._seed_file)
        return key_plain

    async def rotate_key(self, key_id: str, grace_period: int) -> str:
        old = await self.get_key_by_id(key_id)
        if old is None:
            raise ValueError(f"Key {key_id} not found")

        # Generate new plaintext key from the old one + timestamp
        new_plain = f"{old['key_prefix']}{uuid.uuid4().hex[:40]}"
        new_hash = bcrypt.hashpw(new_plain.encode(), bcrypt.gensalt()).decode()

        new_id = f"{key_id}-rotated-{int(time.time())}"
        now = time.time()
        self._keys[new_id] = {
            **old,
            "key_id": new_id,
            "key_hash": new_hash,
            "key_prefix": new_plain[:7],
            "created_at": now,
            "is_active": True,
            "grace_until": old.get("expires_at") or (now + grace_period),
            "expires_at": old.get("expires_at"),
        }
        self._by_hash[new_hash] = new_id

        # Invalidate old
        old["is_active"] = False
        old["rotated_to"] = new_id
        # Remove from lookup so old key fails auth
        if old["key_hash"] in self._by_hash:
            del self._by_hash[old["key_hash"]]

        return new_plain

    async def delete_key(self, key_id: str) -> None:
        record = self._keys.pop(key_id, None)
        if record and record.get("key_hash") in self._by_hash:
            del self._by_hash[record["key_hash"]]

    async def disable_key(self, key_id: str) -> None:
        """Deactivate a key by setting is_active=False."""
        record = self._keys.get(key_id)
        if not record:
            raise ValueError(f"Key {key_id} not found")
        record["is_active"] = False
        # Remove from hash lookup so old key can't authenticate
        if record.get("key_hash") in self._by_hash:
            del self._by_hash[record["key_hash"]]
        # Persist to seed file if configured
        if self._seed_file:
            self._persist_seeds(self._seed_file)

    async def enable_key(self, key_id: str) -> None:
        """Re-activate a previously deactivated key."""
        record = self._keys.get(key_id)
        if not record:
            raise ValueError(f"Key {key_id} not found")
        record["is_active"] = True
        # Re-add to hash lookup so the key can authenticate again
        if record.get("key_hash") and record["key_hash"] not in self._by_hash:
            self._by_hash[record["key_hash"]] = key_id
        # Persist to seed file if configured
        if self._seed_file:
            self._persist_seeds(self._seed_file)

    async def list_keys(self) -> list[dict]:
        return [
            {
                "key_id": r["key_id"],
                "key_prefix": r["key_prefix"],
                "policy_name": r["policy_name"],
                "is_active": r.get("is_active", True),
                "created_at": r.get("created_at"),
                "expires_at": r.get("expires_at"),
                "key_plain": r.get("key_plain"),  # for CLI --reveal
            }
            for r in self._keys.values()
        ]

    async def update_last_used(self, key_id: str) -> None:
        """Update last_used_at for a key."""
        record = self._keys.get(key_id)
        if record:
            record["last_used_at"] = time.time()
            # Persist if seed file is configured
            if self._seed_file:
                self._persist_seeds(self._seed_file)

    def update_last_used_sync(self, key_id: str) -> None:
        """Sync version of :meth:`update_last_used`."""
        return self._run_async(self.update_last_used(key_id))
