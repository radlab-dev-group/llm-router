"""
Redis-backed cache layer for any :class:`KeyStoreInterface`.

Reduces latency by serving lookups from Redis instead of going to the
backend (Vault, disk, …) on every request.
"""

from __future__ import annotations

import asyncio
import json
import time
import random
from typing import Any

import redis

from .interface import KeyStoreInterface


class RedisKeyStoreCache(KeyStoreInterface):
    """Thin cache wrapping any key store backend."""

    # -- cache key templates ----------------------------------------------------
    _HASH_KEY = "auth:key:hash:{hash}"
    _ID_KEY = "auth:key:id:{key_id}"
    _POLICY_KEY = "auth:policy:{policy_name}"

    def __init__(
        self,
        backend: KeyStoreInterface,
        redis_client: redis.Redis | None = None,
        ttl: int = 300,
        jitter: int = 60,
    ) -> None:
        self._backend = backend
        self._redis = redis_client
        self._ttl = ttl
        self._jitter = jitter

    # -- forwarding helpers -----------------------------------------------------
    def _cache_key_for_hash(self, key_hash: str) -> str:
        return self._HASH_KEY.format(hash=key_hash)

    def _cache_key_for_id(self, key_id: str) -> str:
        return self._ID_KEY.format(key_id=key_id)

    def _set_with_jitter(self, key: str, value: str) -> None:
        if self._redis is None:
            return
        ttl = self._ttl + random.randint(0, self._jitter)
        self._redis.setex(key, ttl, value)

    def _invalidate(self, key_id: str, key_hash: str) -> None:
        if self._redis is None:
            return
        self._redis.delete(self._cache_key_for_id(key_id))
        self._redis.delete(self._cache_key_for_hash(key_hash))

    def _record_to_dict(self, record: dict) -> str:
        """Serialize record to JSON string for Redis storage."""
        # Convert sets/tuples to lists for JSON compatibility
        serializable = {}
        for k, v in record.items():
            if isinstance(v, (set, frozenset)):
                serializable[k] = list(v)
            else:
                serializable[k] = v
        return json.dumps(serializable)

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

    # -- KeyStoreInterface ------------------------------------------------------
    async def get_key_by_hash(self, key_hash: str) -> dict | None:
        cache_key = self._cache_key_for_hash(key_hash)

        if self._redis is not None:
            raw = self._redis.get(cache_key)
            if raw is not None:
                return json.loads(raw)

        record = await self._backend.get_key_by_hash(key_hash)
        if record and self._redis is not None:
            self._set_with_jitter(cache_key, self._record_to_dict(record))
        return record

    async def get_key_by_id(self, key_id: str) -> dict | None:
        cache_key = self._cache_key_for_id(key_id)

        if self._redis is not None:
            raw = self._redis.get(cache_key)
            if raw is not None:
                return json.loads(raw)

        record = await self._backend.get_key_by_id(key_id)
        if record and self._redis is not None:
            self._set_with_jitter(cache_key, self._record_to_dict(record))
        return record

    async def create_key(self, record: dict) -> str:
        result = await self._backend.create_key(record)
        # Invalidate caches after write
        if "key_id" in record:
            self._invalidate(record["key_id"], record.get("key_hash", ""))
        return result

    async def rotate_key(self, key_id: str, grace_period: int) -> str:
        old = await self.get_key_by_id(key_id)
        result = await self._backend.rotate_key(key_id, grace_period)
        # Invalidate old key caches
        if old:
            self._invalidate(old["key_id"], old.get("key_hash", ""))
        return result

    async def delete_key(self, key_id: str) -> None:
        old = await self.get_key_by_id(key_id)
        await self._backend.delete_key(key_id)
        if old:
            self._invalidate(key_id, old.get("key_hash", ""))

    async def list_keys(self) -> list[dict]:
        return await self._backend.list_keys()
