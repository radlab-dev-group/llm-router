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
:

    [
      { "key_plain": "sk-llmr-live-...", "policy_name": "developer" },
      { "key_plain": "sk-llmr-live-...",
        "policy_name": "readonly", "expires_at": 1700000000 },
    ]

Keys are stored in a local JSON seed file (default
    ``~/.llm-router/configs/auth/memory-keys.json``).
"""

from __future__ import annotations

import json
import time
import uuid
import bcrypt
import asyncio

import logging as _logging

from pathlib import Path
from typing import Dict, List, Optional

from llm_router_api.core.auth.key_store.interface import KeyStoreInterface
from llm_router_api.core.auth.key_store._record_helpers import (
    apply_rate_limit_override,
    gen_key_prefix,
    gen_sha256_index,
)


class MemoryKeyStore(KeyStoreInterface):
    """
    In-memory store for development / testing.
    """

    def __init__(self, seed_file: Optional[str] = None) -> None:
        self._keys: Dict[str, dict] = {}
        self._by_hash: Dict[str, str] = {}  # bcrypt hash → key_id
        self._by_sha256: Dict[str, str] = (
            {}
        )  # sha256(plaintext) → key_id (O(1) index)
        self._seed_file = seed_file
        if seed_file:
            self._seed_keys(seed_file)

    # -- seed loading ------------------------------
    @staticmethod
    def _load_seeds(seed_file: str) -> List[dict]:
        """
        Load key seed records from a JSON file.

        Each record must carry a verifiable credential: either a
        ``key_hash`` (+``key_index``) or a legacy ``key_plain``.  A record
        with neither is rejected.
        """

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
            if "key_plain" not in rec and "key_hash" not in rec:
                raise ValueError(
                    f"Seed record missing 'key_plain' or 'key_hash': {rec}"
                )
        return records

    def _seed_keys(self, seed_file: str) -> None:
        """
        Load seed records into the key store.

        Plaintext is never retained.  A legacy ``key_plain`` is hashed once at
        load time and then discarded; a ``key_hash``/``key_index`` pair is
        used directly.  The O(1) ``sha256 -> key_id`` index is rebuilt from
        the stored ``key_index``.
        """

        for rec in self._load_seeds(seed_file):
            rec = dict(rec)  # prevent mutating the loaded JSON dict
            key_plain: Optional[str] = rec.pop("key_plain", None)
            key_hash: Optional[str] = rec.get("key_hash")
            key_index: Optional[str] = rec.get("key_index")

            if key_plain is not None:
                # Legacy plaintext seed — hash now, keep only hash + index.
                key_hash = bcrypt.hashpw(
                    key_plain.encode(), bcrypt.gensalt()
                ).decode()
                key_index = gen_sha256_index(key_plain)

            if not key_hash:
                raise ValueError(
                    f"Seed record has neither a usable 'key_plain' nor "
                    f"'key_hash': {rec}"
                )

            key_id = rec.get("key_id", f"seed-{uuid.uuid4().hex[:8]}")
            now = rec.get("created_at", time.time())
            is_active = rec.get("is_active", True)
            api_record = {
                "key_id": key_id,
                "key_hash": key_hash,
                "key_index": key_index,
                "key_prefix": rec.get("key_prefix")
                or (gen_key_prefix(key_plain) if key_plain else ""),
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
            if key_index is not None:
                self._by_sha256[key_index] = key_id

    def _persist_seeds(self, seed_file: str) -> None:
        """
        Write all current keys back to the seed file.

        Only the bcrypt ``key_hash`` and the ``key_index`` (SHA-256) are
        persisted — the plaintext is **never** written to disk.  Deleted keys
        (popped from ``_keys``) are dropped; disabled keys
        (``is_active=False``) survive so that ``enable`` works after a restart.
        """
        path = Path(seed_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        out: List[dict] = [
            {
                "key_id": rec["key_id"],
                "key_hash": rec.get("key_hash"),
                "key_index": rec.get("key_index"),
                "key_prefix": rec.get("key_prefix", ""),
                "policy_name": rec["policy_name"],
                "policy_override": rec.get("policy_override"),
                "is_active": rec.get("is_active", True),
                "expires_at": rec.get("expires_at"),
                "created_at": rec.get("created_at"),
                "metadata": rec.get("metadata", {}),
            }
            for rec in self._keys.values()
        ]
        path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    # -- lookups ----------------------------------------------------------------
    async def get_key_by_hash(self, key_hash: str) -> Optional[dict]:
        key_id = self._by_hash.get(key_hash)
        if key_id is None:
            return None
        record = self._keys.get(key_id)
        if record and not record.get("is_active"):
            return None
        return record

    def get_key_by_hash_sync(self, key_hash: str) -> Optional[dict]:
        return asyncio.run(self.get_key_by_hash(key_hash))

    async def get_key_by_id(self, key_id: str) -> Optional[dict]:
        record = self._keys.get(key_id)
        if record and not record.get("is_active"):
            return None
        return record

    async def get_key_by_plain(self, key_plain: str) -> Optional[dict]:
        """
        Look up a key record by its **plaintext** key.

        O(1) via the ``sha256(plaintext) -> key_id`` index, followed by a
        single constant-time ``bcrypt.checkpw`` against the stored hash.
        (Previously this was a linear scan comparing plaintexts with ``==`` —
        both a per-attempt DoS vector and a timing side-channel.)
        """

        logger = _logging.getLogger(__name__)
        index_key = gen_sha256_index(key_plain)
        key_id = self._by_sha256.get(index_key)
        if key_id is None:
            logger.warning(
                "get_key_by_plain: NO MATCH for key with prefix=%s",
                key_plain[:7] if len(key_plain) > 6 else key_plain,
            )
            return None
        record = self._keys.get(key_id)
        if record is None or not record.get("is_active", True):
            return None
        stored_hash = record.get("key_hash")
        if not stored_hash or not bcrypt.checkpw(
            key_plain.encode(), stored_hash.encode()
        ):
            return None
        logger.info("get_key_by_plain: MATCH (id=%s)", key_id[:8])
        return record

    def get_key_by_plain_sync(self, key_plain: str) -> Optional[dict]:
        """
        Synchronous version of :meth:`get_key_by_plain`.
        """

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
        key_index = gen_sha256_index(key_plain)

        key_id = record.get("key_id", f"dev-{uuid.uuid4().hex[:8]}")
        now = time.time()
        api_record = {
            "key_id": key_id,
            "key_hash": key_hash,
            "key_index": key_index,
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
        self._by_sha256[key_index] = key_id
        # Persist to seed file if one is configured (hash + index, no plaintext)
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
        new_index = gen_sha256_index(new_plain)

        new_id = f"{key_id}-rotated-{int(time.time())}"
        now = time.time()
        new_record = {
            **old,
            "key_id": new_id,
            "key_hash": new_hash,
            "key_index": new_index,
            "key_prefix": gen_key_prefix(new_plain),
            "created_at": now,
            "is_active": True,
            "grace_until": old.get("expires_at") or (now + grace_period),
            "expires_at": old.get("expires_at"),
        }
        new_record.pop("key_plain", None)  # never carry plaintext forward
        self._keys[new_id] = new_record
        self._by_hash[new_hash] = new_id
        self._by_sha256[new_index] = new_id

        # Invalidate old
        old["is_active"] = False
        old["rotated_to"] = new_id
        # Remove from lookups so the old key fails auth
        if old["key_hash"] in self._by_hash:
            del self._by_hash[old["key_hash"]]
        old_index = old.get("key_index")
        if old_index and self._by_sha256.get(old_index) == key_id:
            del self._by_sha256[old_index]

        return new_plain

    async def delete_key(self, key_id: str) -> None:
        record = self._keys.pop(key_id, None)
        if record and record.get("key_hash") in self._by_hash:
            del self._by_hash[record["key_hash"]]
        if record:
            old_index = record.get("key_index")
            if old_index and self._by_sha256.get(old_index) == key_id:
                del self._by_sha256[old_index]

    async def disable_key(self, key_id: str) -> None:
        """
        Deactivate a key by setting is_active=False.
        """

        record = self._keys.get(key_id)
        if not record:
            raise ValueError(f"Key {key_id} not found")
        record["is_active"] = False
        # Remove from lookups so the key can't authenticate
        if record.get("key_hash") in self._by_hash:
            del self._by_hash[record["key_hash"]]
        old_index = record.get("key_index")
        if old_index and self._by_sha256.get(old_index) == key_id:
            del self._by_sha256[old_index]
        # Persist to seed file if configured
        if self._seed_file:
            self._persist_seeds(self._seed_file)

    async def enable_key(self, key_id: str) -> None:
        """
        Re-activate a previously deactivated key.
        """

        record = self._keys.get(key_id)
        if not record:
            raise ValueError(f"Key {key_id} not found")
        record["is_active"] = True
        # Re-add to lookups so the key can authenticate again
        if record.get("key_hash") and record["key_hash"] not in self._by_hash:
            self._by_hash[record["key_hash"]] = key_id
        index = record.get("key_index")
        if index is not None:
            self._by_sha256[index] = key_id
        # Persist to seed file if configured
        if self._seed_file:
            self._persist_seeds(self._seed_file)

    async def update_policy_override(
        self, key_id: str, rate_limit: Optional[int]
    ) -> None:
        """
        Set or clear the ``rate_limit`` policy override (see interface).
        """
        record = self._keys.get(key_id)
        if record is None:
            raise ValueError(f"Key {key_id} not found")
        self._keys[key_id] = apply_rate_limit_override(record, rate_limit)
        if self._seed_file:
            self._persist_seeds(self._seed_file)

    async def list_keys(self) -> List[dict]:
        # Note: ``key_plain`` is intentionally NOT exposed — the plaintext is
        # never retained, so there is nothing to "reveal".
        return [
            {
                "key_id": r["key_id"],
                "key_prefix": r["key_prefix"],
                "policy_name": r["policy_name"],
                "is_active": r.get("is_active", True),
                "created_at": r.get("created_at"),
                "expires_at": r.get("expires_at"),
            }
            for r in self._keys.values()
        ]

    async def update_last_used(self, key_id: str) -> None:
        """
        Update last_used_at for a key.
        """

        record = self._keys.get(key_id)
        if record:
            record["last_used_at"] = time.time()
            # Persist if seed file is configured
            if self._seed_file:
                self._persist_seeds(self._seed_file)

    def update_last_used_sync(self, key_id: str) -> None:
        """
        Sync version of :meth:`update_last_used`.
        """

        return self._run_async(self.update_last_used(key_id))
