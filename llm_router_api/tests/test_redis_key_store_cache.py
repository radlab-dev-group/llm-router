"""
Unit tests for ``llm_router_api.core.auth.key_store.redis_cache.RedisKeyStoreCache``.

The cache is exercised against a fakeredis instance and a lightweight async
fake backend.  No real Redis/network is required.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import asyncio  # noqa: E402
import json  # noqa: E402

import fakeredis  # noqa: E402

from llm_router_api.core.auth.key_store.redis_cache import (  # noqa: E402
    RedisKeyStoreCache,
)


class FakeBackend:
    """Async stand-in for a KeyStoreInterface backend."""

    def __init__(self):
        self.by_hash = {}
        self.by_id = {}
        self.by_plain = {}
        self.calls = []
        self.created = []
        self.rotated = []
        self.disabled = []
        self.enabled = []
        self.deleted = []
        self.overrides = []

    async def get_key_by_hash(self, key_hash):
        self.calls.append(("get_key_by_hash", key_hash))
        return self.by_hash.get(key_hash)

    def get_key_by_hash_sync(self, key_hash):
        return self.get_key_by_hash(key_hash)  # type: ignore[no-any-return]

    async def get_key_by_id(self, key_id):
        self.calls.append(("get_key_by_id", key_id))
        return self.by_id.get(key_id)

    async def get_key_by_plain(self, key_plain):
        self.calls.append(("get_key_by_plain", key_plain))
        return self.by_plain.get(key_plain)

    async def create_key(self, record):
        self.created.append(record)
        return record.get("key_id", "new")

    async def rotate_key(self, key_id, grace_period):
        self.rotated.append((key_id, grace_period))
        return "new-hash"

    async def disable_key(self, key_id):
        self.disabled.append(key_id)

    async def enable_key(self, key_id):
        self.enabled.append(key_id)

    async def delete_key(self, key_id):
        self.deleted.append(key_id)

    async def list_keys(self):
        return list(self.by_id.values())

    async def update_policy_override(self, key_id, rate_limit):
        self.overrides.append((key_id, rate_limit))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make(backend, redis, ttl=300, jitter=60):
    return RedisKeyStoreCache(backend, redis_client=redis, ttl=ttl, jitter=jitter)


class TestGetKeyByHash:
    def test_miss_populates_cache(self):
        backend = FakeBackend()
        backend.by_hash["h1"] = {"key_id": "k1", "is_active": True}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)

        result = _run(cache.get_key_by_hash("h1"))
        assert result == {"key_id": "k1", "is_active": True}
        assert redis.get("auth:key:hash:h1") is not None

    def test_hit_skips_backend(self):
        backend = FakeBackend()
        backend.by_hash["h1"] = {"key_id": "k1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        _run(cache.get_key_by_hash("h1"))

        backend.calls.clear()
        _run(cache.get_key_by_hash("h1"))
        assert backend.calls == []

    def test_ttl_within_range(self):
        backend = FakeBackend()
        backend.by_hash["h1"] = {"key_id": "k1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        ttl, jitter = 300, 60
        cache = _make(backend, redis, ttl=ttl, jitter=jitter)
        _run(cache.get_key_by_hash("h1"))
        ttl_set = redis.ttl("auth:key:hash:h1")
        assert ttl <= ttl_set <= ttl + jitter


class TestGetKeyId:
    def test_miss_and_hit(self):
        backend = FakeBackend()
        backend.by_id["k9"] = {"key_id": "k9"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        assert _run(cache.get_key_by_id("k9")) == {"key_id": "k9"}
        backend.calls.clear()
        _run(cache.get_key_by_id("k9"))
        assert backend.calls == []


class TestRecordToDict:
    def test_set_converted_to_list(self):
        cache = _make(FakeBackend(), fakeredis.FakeRedis())
        out = cache._record_to_dict({"whitelist": {"a", "b"}, "n": 1})
        data = json.loads(out)
        assert sorted(data["whitelist"]) == ["a", "b"]
        assert data["n"] == 1

    def test_round_trip(self):
        cache = _make(FakeBackend(), fakeredis.FakeRedis())
        record = {"key_id": "k", "policy_override": None, "flags": {"x"}}
        data = json.loads(cache._record_to_dict(record))
        assert data["key_id"] == "k"
        assert data["flags"] == ["x"]


class TestInvalidate:
    def test_disable_invalidates_both_keys(self):
        backend = FakeBackend()
        backend.by_id["k1"] = {"key_id": "k1", "key_hash": "h1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        _run(cache.get_key_by_id("k1"))
        assert redis.get("auth:key:id:k1") is not None

        _run(cache.disable_key("k1"))
        assert backend.disabled == ["k1"]
        assert redis.get("auth:key:id:k1") is None
        assert redis.get("auth:key:hash:h1") is None

    def test_enable_invalidates(self):
        backend = FakeBackend()
        backend.by_id["k1"] = {"key_id": "k1", "key_hash": "h1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        _run(cache.get_key_by_id("k1"))
        _run(cache.enable_key("k1"))
        assert backend.enabled == ["k1"]
        assert redis.get("auth:key:id:k1") is None

    def test_delete_invalidates(self):
        backend = FakeBackend()
        backend.by_id["k1"] = {"key_id": "k1", "key_hash": "h1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        _run(cache.get_key_by_id("k1"))
        _run(cache.delete_key("k1"))
        assert backend.deleted == ["k1"]
        assert redis.get("auth:key:id:k1") is None

    def test_rotate_invalidates_old(self):
        backend = FakeBackend()
        backend.by_id["k1"] = {"key_id": "k1", "key_hash": "h1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        _run(cache.get_key_by_id("k1"))
        result = _run(cache.rotate_key("k1", 60))
        assert result == "new-hash"
        assert backend.rotated == [("k1", 60)]
        assert redis.get("auth:key:id:k1") is None

    def test_update_policy_override_invalidates(self):
        backend = FakeBackend()
        backend.by_id["k1"] = {"key_id": "k1", "key_hash": "h1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        _run(cache.get_key_by_id("k1"))
        _run(cache.update_policy_override("k1", 42))
        assert backend.overrides == [("k1", 42)]
        assert redis.get("auth:key:id:k1") is None

    def test_create_key_invalidates(self):
        backend = FakeBackend()
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        redis.set("auth:key:id:new", "{}")
        result = _run(cache.create_key({"key_id": "new", "key_hash": "h9"}))
        assert result == "new"
        assert redis.get("auth:key:id:new") is None


class TestGetKeyByPlain:
    def test_always_hits_backend(self):
        backend = FakeBackend()
        backend.by_plain["sk-x"] = {"key_id": "k1"}
        redis = fakeredis.FakeRedis(decode_responses=True)
        cache = _make(backend, redis)
        assert _run(cache.get_key_by_plain("sk-x")) == {"key_id": "k1"}
        backend.calls.clear()
        _run(cache.get_key_by_plain("sk-x"))
        assert ("get_key_by_plain", "sk-x") in backend.calls


class TestNoRedis:
    def test_works_without_redis(self):
        backend = FakeBackend()
        backend.by_hash["h1"] = {"key_id": "k1"}
        cache = _make(backend, None)
        assert _run(cache.get_key_by_hash("h1")) == {"key_id": "k1"}
        backend.calls.clear()
        _run(cache.get_key_by_hash("h1"))
        assert backend.calls == [("get_key_by_hash", "h1")]


class TestSyncWrappers:
    def test_get_key_by_hash_sync(self):
        backend = FakeBackend()
        backend.by_hash["h1"] = {"key_id": "k1"}
        cache = _make(backend, fakeredis.FakeRedis(decode_responses=True))
        assert cache.get_key_by_hash_sync("h1") == {"key_id": "k1"}

    def test_get_key_by_plain_sync(self):
        backend = FakeBackend()
        backend.by_plain["sk-p"] = {"key_id": "k2"}
        cache = _make(backend, fakeredis.FakeRedis(decode_responses=True))
        assert cache.get_key_by_plain_sync("sk-p") == {"key_id": "k2"}
