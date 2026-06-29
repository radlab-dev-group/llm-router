"""
Redis key store — stores API keys directly in Redis.

Uses a Redis **string** (JSON-serialized) per key under ``secret:llm-router:api-keys:<key_id>``.
Suitable for deployments without HashiCorp Vault.
"""

from __future__ import annotations

import json
import time
import uuid
import redis
import bcrypt
import asyncio


from llm_router_api.core.auth.key_store.interface import KeyStoreInterface

_DEFAULT_REDIS_PREFIX = "secret:llm-router:api-keys"


class RedisKeyStore(KeyStoreInterface):
    """Store API keys in Redis."""

    def __init__(
        self,
        redis_client: redis.Redis | None = None,
        redis_host: str | None = None,
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: str | None = None,
        prefix: str = _DEFAULT_REDIS_PREFIX,
    ) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            self._redis = redis.Redis(
                host=redis_host or "127.0.0.1",
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                password=redis_password,
            )
        self._prefix = prefix

    def _key(self, key_id: str) -> str:
        return f"{self._prefix}:{key_id}"

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

    def get_key_by_hash_sync(self, key_hash: str) -> dict | None:
        return self._run_async(self.get_key_by_hash(key_hash))

    async def get_key_by_plain(self, key_plain: str) -> dict | None:
        """Look up a key record by its plaintext key using bcrypt.checkpw."""
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(
                cursor, match=f"{self._prefix}:*", count=100
            )
            for key_name in keys:
                raw = self._redis.get(key_name)
                if raw:
                    record = json.loads(raw)
                    stored_hash = record.get("key_hash")
                    if stored_hash and bcrypt.checkpw(
                        key_plain.encode(), stored_hash.encode()
                    ):
                        return record
            if cursor == 0:
                break
        return None

    def get_key_by_plain_sync(self, key_plain: str) -> dict | None:
        return self._run_async(self.get_key_by_plain(key_plain))

    async def get_key_by_hash(self, key_hash: str) -> dict | None:
        # Scan all keys looking for a matching hash
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(
                cursor, match=f"{self._prefix}:*", count=100
            )
            for key in keys:
                raw = self._redis.get(key)
                if raw:
                    record = json.loads(raw)
                    if record.get("key_hash") == key_hash and record.get(
                        "is_active"
                    ):
                        return record
            if cursor == 0:
                break
        return None

    async def get_key_by_id(self, key_id: str) -> dict | None:
        raw = self._redis.get(self._key(key_id))
        if not raw:
            return None
        record = json.loads(raw)
        if not record.get("is_active"):
            return None
        return record

    async def create_key(self, record: dict) -> str:
        record = dict(record)  # prevent mutating caller's dict
        key_plain: str = record.pop("key_plain")
        key_hash = bcrypt.hashpw(key_plain.encode(), bcrypt.gensalt()).decode()

        key_id = record.get("key_id", f"key-{uuid.uuid4().hex[:8]}")
        now = time.time()
        api_record = {
            "key_id": key_id,
            "key_hash": key_hash,
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
        self._redis.set(self._key(key_id), json.dumps(api_record))
        return key_plain

    async def rotate_key(self, key_id: str, grace_period: int) -> str:
        old_raw = self._redis.get(self._key(key_id))
        if not old_raw:
            raise ValueError(f"Key {key_id} not found")

        old = json.loads(old_raw)
        new_plain = f"{old['key_prefix']}{uuid.uuid4().hex[:40]}"
        new_hash = bcrypt.hashpw(new_plain.encode(), bcrypt.gensalt()).decode()
        new_id = f"{key_id}-rotated-{int(time.time())}"
        now = time.time()

        new_record = {
            **old,
            "key_id": new_id,
            "key_hash": new_hash,
            "key_prefix": new_plain[:7],
            "created_at": now,
            "is_active": True,
            "grace_until": old.get("expires_at") or (now + grace_period),
        }
        self._redis.set(self._key(new_id), json.dumps(new_record))

        old["is_active"] = False
        old["rotated_to"] = new_id
        self._redis.set(self._key(key_id), json.dumps(old))

        return new_plain

    async def disable_key(self, key_id: str) -> None:
        """Deactivate a key by setting is_active=False."""
        raw = self._redis.get(self._key(key_id))
        if not raw:
            raise ValueError(f"Key {key_id} not found")
        record = json.loads(raw)
        record["is_active"] = False
        self._redis.set(self._key(key_id), json.dumps(record))

    async def enable_key(self, key_id: str) -> None:
        """Re-activate a previously deactivated key."""
        raw = self._redis.get(self._key(key_id))
        if not raw:
            raise ValueError(f"Key {key_id} not found")
        record = json.loads(raw)
        record["is_active"] = True
        self._redis.set(self._key(key_id), json.dumps(record))

    async def delete_key(self, key_id: str) -> None:
        self._redis.delete(self._key(key_id))

    async def list_keys(self) -> list[dict]:
        result = []
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(
                cursor, match=f"{self._prefix}:*", count=100
            )
            for key in keys:
                raw = self._redis.get(key)
                if raw:
                    record = json.loads(raw)
                    result.append(
                        {
                            "key_id": record["key_id"],
                            "key_prefix": record["key_prefix"],
                            "policy_name": record["policy_name"],
                            "is_active": record["is_active"],
                            "created_at": record["created_at"],
                            "expires_at": record.get("expires_at"),
                        }
                    )
            if cursor == 0:
                break
        return result

    async def update_last_used(self, key_id: str) -> None:
        """Update last_used_at for a key."""
        raw = self._redis.get(self._key(key_id))
        if not raw:
            return
        record = json.loads(raw)
        record["last_used_at"] = time.time()
        self._redis.set(self._key(key_id), json.dumps(record))

    def update_last_used_sync(self, key_id: str) -> None:
        """Sync version of :meth:`update_last_used`."""
        return self._run_async(self.update_last_used(key_id))
