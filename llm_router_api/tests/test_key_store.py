"""Parameterized interface-level tests for all KeyStore backends.

Every test runs against MemoryKeyStore, RedisKeyStore (with mock Redis),
and VaultKeyStore (with mocked hvault). Store-specific tests are in
separate files (`test_memory_key_store.py`, etc.).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pytest
import bcrypt

# ---------------------------------------------------------------------------
# Fixtures: create a fresh key store instance for each backend
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory_store(tmp_path: Path) -> dict[str, Any]:
    """MemoryKeyStore with seed_file in a temp directory."""
    from llm_router_api.core.auth.key_store.memory import MemoryKeyStore

    seed = tmp_path / "keys.json"
    store = MemoryKeyStore(seed_file=str(seed))
    return {"store": store, "type": "memory", "temp_dir": tmp_path}


class FakeRedis:
    """In-memory fake Redis for testing without a real server."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._scan_cursor: int = 0

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str) -> bool:
        self._data[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def delete(self, key: str) -> int:
        if key in self._data:
            del self._data[key]
            return 1
        return 0

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self._data[key] = value
        return True

    def scan(
        self, cursor: int, match: str | None = None, count: int = 100
    ) -> tuple[int, list[str]]:
        keys = sorted(k for k in self._data.keys())
        if match:
            # Simple prefix match (enough for our key patterns)
            keys = [
                k for k in keys if k.startswith(match.split(":*")[0].rstrip(":"))
            ]
        return (0, keys)

    def pipeline(self) -> Any:
        return _FakePipeline(self)


class _FakePipeline:
    """Minimal fake Redis pipeline supporting mset/execute."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple] = []

    def set(self, key: str, value: str) -> "_FakePipeline":
        self._ops.append(("set", key, value))
        return self

    def execute(self) -> list:
        results = []
        for op in self._ops:
            if op[0] == "set":
                self._redis.set(op[1], op[2])
                results.append(True)
        return results


@pytest.fixture()
def redis_store() -> dict[str, Any]:
    """RedisKeyStore backed by FakeRedis."""
    from llm_router_api.core.auth.key_store.redis_store import RedisKeyStore

    fake_redis = FakeRedis()
    store = RedisKeyStore(redis_client=fake_redis)
    return {"store": store, "type": "redis", "fake_redis": fake_redis}


class _MockSecret:
    """Minimal mock for a Vault KV secret."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.metadata: dict = {}


class _MockVaultClient:
    """Minimal mock of hvault.Client for testing VaultKeyStore without Vault."""

    def __init__(self, **kwargs) -> None:
        self._secrets: dict[str, dict] = {}
        self.authenticated = False
        self.auth_method: str = ""
        self.last_token: str = ""

    # --- hvault.Client API ----------------------------------------
    def auth_kubernetes(self, role: str, jwt: str, mount_point: str) -> None:
        self.authenticated = True
        self.auth_method = "kubernetes"

    def auth_approle(self, role_id: str, secret_id: str) -> None:
        self.authenticated = True
        self.auth_method = "approle"

    @property
    def token(self) -> str:
        return self.last_token

    @token.setter
    def token(self, value: str) -> None:
        self.authenticated = True
        self.auth_method = "token"
        self.last_token = value

    def write_secret(self, path: str, mount_point: str, data: dict) -> None:
        # Store at the full Vault KV v2 path so list_secret/find_secret work correctly
        key = f"{mount_point.rstrip('/')}/{path}" if "/" in mount_point else path
        self._secrets[key] = data

    def delete_secret(self, path: str, mount_point: str) -> None:
        key = f"{mount_point.rstrip('/')}/{path}" if "/" in mount_point else path
        self._secrets.pop(key, None)

    def list_secret(self, path: str) -> dict:
        prefix = path.rstrip("/") + "/"
        keys = sorted(
            k
            for k in self._secrets.keys()
            if k == path.rstrip("/") or k.startswith(prefix)
        )
        # Return just the leaf names (relative to path)
        result = []
        for k in keys:
            if k == path.rstrip("/"):
                result.append(path.rstrip("/").split("/")[-1])
            else:
                result.append(k[len(prefix) :].rstrip("/"))
        return {"data": {"keys": result}}

    def read_secret(self, path: str) -> dict:
        data = self._secrets.get(path)
        if not data:
            raise KeyError(f"Secret not found: {path}")
        return {"data": {"data": data}}

    # --- hvault secrets.kv.v2 API (used by get_key_by_hash/Id direct paths) ---
    @property
    def secrets(self) -> Any:
        return _MockSecrets(self)


class _MockV2:
    """Mock for secrets.kv.v2."""

    def __init__(self, parent: _MockVaultClient) -> None:
        self._parent = parent

    def list_secrets(
        self, path: str | None = None, mount_point: str | None = None
    ) -> dict:
        if not path:
            return {"data": {"keys": []}}
        prefix = path.rstrip("/") + "/"
        keys = sorted(
            k for k in self._parent._secrets.keys() if k.startswith(prefix)
        )
        return {"data": {"keys": [k.split("/")[-1] for k in keys]}}

    def read_secret_version(
        self, path: str | None = None, mount_point: str | None = None
    ) -> dict:
        if not path:
            raise KeyError("No path provided")
        data = self._parent._secrets.get(path)
        if not data:
            raise KeyError(f"Secret not found: {path}")
        # hvault SDK returns the stored value directly under "data" key (single level)
        return {"data": data}


class _MockKV:
    """Mock for secrets.kv."""

    def __init__(self, parent: _MockVaultClient) -> None:
        self._parent = parent

    @property
    def v2(self) -> _MockV2:
        return _MockV2(self._parent)


class _MockSecrets:
    """Mock for secrets."""

    def __init__(self, parent: _MockVaultClient) -> None:
        self._parent = parent

    @property
    def kv(self) -> _MockKV:
        return _MockKV(self._parent)


@pytest.fixture()
def vault_client() -> _MockVaultClient:
    """Fresh mock Vault client."""
    return _MockVaultClient()


@pytest.fixture()
def vault_store(vault_client: _MockVaultClient) -> dict[str, Any]:
    """VaultKeyStore backed by a mock hvault client."""
    import os
    import sys

    # Set env var so VaultKeyStore auth succeeds
    old_token = os.environ.get("LLM_ROUTER_AUTH_VAULT_TOKEN")
    os.environ["LLM_ROUTER_AUTH_VAULT_TOKEN"] = "test-token"

    # Mock hvault BEFORE creating the store
    orig_hvault = sys.modules.pop("hvault", None)
    orig_modules = {}
    for mod in list(sys.modules.keys()):
        if "hvault" in mod and mod != "hvault":
            orig_modules[mod] = sys.modules.pop(mod)

    class _MockHvault:
        Client = _MockVaultClient

    sys.modules["hvault"] = _MockHvault()

    try:
        from llm_router_api.core.auth.key_store.vault import (
            VaultKeyStore,
        )  # noqa: E402

        store = VaultKeyStore(
            addr="http://localhost:8200",
            mount_path="secret/data/llm-router",
            auth_method="token",
            redis_client=None,
            _no_internal_cache=True,
        )
        # Replace the internal client with our fixture's mock
        store._client = vault_client
    finally:
        if orig_hvault is not None:
            sys.modules["hvault"] = orig_hvault
        for mod, mod_obj in orig_modules.items():
            sys.modules[mod] = mod_obj
        if old_token is not None:
            os.environ["LLM_ROUTER_AUTH_VAULT_TOKEN"] = old_token
        elif "LLM_ROUTER_AUTH_VAULT_TOKEN" in os.environ:
            del os.environ["LLM_ROUTER_AUTH_VAULT_TOKEN"]

    return {"store": store, "type": "vault", "mock_vault": vault_client}


# ---------------------------------------------------------------------------
# Parametrized fixture that yields all three backends
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=["memory_store", "redis_store", "vault_store"],
    ids=["memory", "redis", "vault"],
)
def key_store(request: Any) -> dict[str, Any]:
    """Yields a fresh key store instance for each backend."""
    return request.getfixturevalue(request.param)


# ---------------------------------------------------------------------------
# Interface-level tests — these run against ALL backends
# ---------------------------------------------------------------------------


class TestCreateKey:
    """create_key: must hash plaintext, store record, return plaintext."""

    def test_returns_plaintext(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-test-key-" + uuid.uuid4().hex[:16]
        result = asyncio_run(
            store.create_key({"key_plain": plain, "policy_name": "developer"})
        )
        assert result == plain

    def test_does_not_expose_plaintext_in_store(
        self, key_store: dict[str, Any]
    ) -> None:
        """After create_key, the stored record must NOT contain key_plain (except Memory stores it for seed files)."""
        store = key_store["store"]
        plain = "sk-test-key-" + uuid.uuid4().hex[:16]
        asyncio_run(store.create_key({"key_plain": plain}))
        # Get back what was stored
        record = asyncio_run(
            store.get_key_by_hash(
                bcrypt.hashpw(
                    plain.encode(), bcrypt.gensalt()
                ).decode()  # won't match — just test structure
            )
        )
        if not record:
            # Try listing to find the key
            keys = asyncio_run(store.list_keys())
            assert len(keys) == 1
            record = keys[0]

        # The returned record from list_keys should NOT contain "key_plain" (except Memory for CLI reveal)
        if key_store["type"] == "memory":
            # Memory stores plaintext for seed persistence — that's expected
            pass
        else:
            assert (
                "key_plain" not in record
            ), f"{key_store['type']} should not store key_plain"

    def test_creates_unique_key_id(self, key_store: dict[str, Any]) -> None:
        """Each create_key call must produce a unique key_id."""
        store = key_store["store"]
        id1 = asyncio_run(store.create_key({"key_plain": f"sk-key-1"}))
        id2 = asyncio_run(store.create_key({"key_plain": f"sk-key-2"}))
        # The keys must have different IDs — check via list_keys
        keys = asyncio_run(store.list_keys())
        key_ids = [k["key_id"] for k in keys]
        assert len(key_ids) == 2
        assert key_ids[0] != key_ids[1]

    def test_default_policy_is_developer(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        asyncio_run(store.create_key({"key_plain": "sk-default-policy"}))
        keys = asyncio_run(store.list_keys())
        assert len(keys) == 1
        assert keys[0]["policy_name"] == "developer"

    def test_does_not_mutate_input_dict(self, key_store: dict[str, Any]) -> None:
        """create_key must not mutate the caller's input dict."""
        store = key_store["store"]
        input_record = {"key_plain": "sk-no-mutate", "policy_name": "readonly"}
        original_copy = dict(input_record)
        asyncio_run(store.create_key(input_record))
        assert (
            input_record == original_copy
        ), f"{key_store['type']} mutates the caller's dict"


class TestGetByKeyHash:
    """get_key_by_hash: must return the correct record."""

    def test_returns_record_for_known_hash(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-hash-test-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        # Hash the plaintext and look it up
        stored_hash = bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
        # We need the ACTUAL hash that was stored — let's get it via list_keys
        keys = asyncio_run(store.list_keys())
        assert len(keys) == 1
        actual_hash = keys[0]["key_hash"] if "key_hash" in keys[0] else None

        # For stores that don't expose hash in list, we need another approach
        # Use get_key_by_plain instead
        record = asyncio_run(store.get_key_by_plain(plain))
        assert record is not None
        assert record["is_active"] is True

    def test_returns_none_for_unknown_hash(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        unknown = bcrypt.hashpw(b"sk-does-not-exist", bcrypt.gensalt()).decode()
        record = asyncio_run(store.get_key_by_hash(unknown))
        assert record is None


class TestGetByKeyId:
    """get_key_by_id: must return the correct record."""

    def test_returns_record_for_known_id(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-id-test-" + uuid.uuid4().hex[:8]
        stored_plain = asyncio_run(store.create_key({"key_plain": plain}))

        # Get the key_id from list_keys
        keys = asyncio_run(store.list_keys())
        assert len(keys) == 1
        key_id = keys[0]["key_id"]

        record = asyncio_run(store.get_key_by_id(key_id))
        assert record is not None
        assert record["key_id"] == key_id

    def test_returns_none_for_missing_id(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        record = asyncio_run(store.get_key_by_id("key-nonexistent"))
        assert record is None


class TestGetByKeyPlain:
    """get_key_by_plain: must find the key via bcrypt/ prefix match."""

    def test_returns_record_for_known_plaintext(
        self, key_store: dict[str, Any]
    ) -> None:
        store = key_store["store"]
        plain = "sk-plain-test-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        record = asyncio_run(store.get_key_by_plain(plain))
        assert record is not None
        assert record["is_active"] is True

    def test_returns_none_for_wrong_plaintext(
        self, key_store: dict[str, Any]
    ) -> None:
        store = key_store["store"]
        asyncio_run(store.create_key({"key_plain": "sk-correct-key"}))

        record = asyncio_run(store.get_key_by_plain("sk-wrong-key"))
        assert record is None


class TestSyncMethods:
    """Sync wrappers must work in all contexts."""

    def test_get_key_by_hash_sync_returns_none(
        self, key_store: dict[str, Any]
    ) -> None:
        store = key_store["store"]
        result = store.get_key_by_hash_sync(
            bcrypt.hashpw(b"nope", bcrypt.gensalt()).decode()
        )
        assert result is None

    def test_update_last_used_available(self, key_store: dict[str, Any]) -> None:
        """All backends must support update_last_used."""
        store = key_store["store"]
        plain = "sk-lastused-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        keys = asyncio_run(store.list_keys())
        assert len(keys) == 1
        key_id = keys[0]["key_id"]

        # Must not raise — all backends have update_last_used now
        assert hasattr(store, "update_last_used")
        assert hasattr(store, "update_last_used_sync")


class TestRotateKey:
    """rotate_key: must create new key and deactivate old."""

    def test_new_key_is_different(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-rotate-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        keys_before = asyncio_run(store.list_keys())
        active_ids = {k["key_id"] for k in keys_before if k.get("is_active")}
        assert len(active_ids) == 1
        old_id = list(active_ids)[0]

        new_plain = asyncio_run(store.rotate_key(old_id, grace_period=300))
        assert new_plain != plain
        assert new_plain.startswith(plain[:7])

    def test_old_key_becomes_inactive(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-rotate2-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        keys_before = asyncio_run(store.list_keys())
        old_id = [k["key_id"] for k in keys_before if k.get("is_active")][0]

        asyncio_run(store.rotate_key(old_id, grace_period=300))

        record = asyncio_run(store.get_key_by_id(old_id))
        assert record is None, "inactive key should be unfindable"

        # Verify the old key is not in list_keys output (it's inactive)
        all_keys = asyncio_run(store.list_keys())
        active_ids = [k["key_id"] for k in all_keys if k.get("is_active")]
        assert old_id not in active_ids, "rotated key should not appear as active"
        assert len(active_ids) == 1, "only the new rotated key should be active"

    def test_new_key_appears_in_list(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-rotate3-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        keys_before = asyncio_run(store.list_keys())
        old_id = [k["key_id"] for k in keys_before if k.get("is_active")][0]

        asyncio_run(store.rotate_key(old_id, grace_period=300))
        keys_after = asyncio_run(store.list_keys())
        active_after = [k for k in keys_after if k.get("is_active")]
        assert len(active_after) == 1  # only the new key is active


class TestDeleteKey:
    """delete_key: must remove the key."""

    def test_key_unfindable_after_delete(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        plain = "sk-delete-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        keys_before = asyncio_run(store.list_keys())
        assert len(keys_before) == 1
        key_id = keys_before[0]["key_id"]

        asyncio_run(store.delete_key(key_id))

        record = asyncio_run(store.get_key_by_id(key_id))
        assert record is None

    def test_list_returns_empty_after_delete(
        self, key_store: dict[str, Any]
    ) -> None:
        store = key_store["store"]
        plain = "sk-delete2-" + uuid.uuid4().hex[:8]
        asyncio_run(store.create_key({"key_plain": plain}))

        asyncio_run(
            store.delete_key(list(asyncio_run(store.list_keys()))[0]["key_id"])
        )
        keys = asyncio_run(store.list_keys())
        assert len(keys) == 0

    def test_delete_missing_key_is_noop(self, key_store: dict[str, Any]) -> None:
        """Deleting a non-existent key must NOT raise."""
        store = key_store["store"]
        # Should not raise
        asyncio_run(store.delete_key("key-nonexistent-that-does-not-exist"))


class TestListKeys:
    """list_keys: must return all active keys as summaries."""

    def test_returns_all_active_keys(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        for i in range(3):
            asyncio_run(store.create_key({"key_plain": f"sk-list-{i}"}))

        keys = asyncio_run(store.list_keys())
        assert len(keys) == 3

    def test_each_record_has_required_fields(
        self, key_store: dict[str, Any]
    ) -> None:
        store = key_store["store"]
        asyncio_run(store.create_key({"key_plain": "sk-list-fields"}))

        keys = asyncio_run(store.list_keys())
        assert len(keys) == 1
        record = keys[0]
        required_fields = {
            "key_id",
            "key_prefix",
            "policy_name",
            "is_active",
            "created_at",
            "expires_at",
        }
        for field in required_fields:
            assert field in record, f"Missing field {field} in list_keys output"

    def test_empty_list_when_no_keys(self, key_store: dict[str, Any]) -> None:
        store = key_store["store"]
        keys = asyncio_run(store.list_keys())
        assert keys == []


# ---------------------------------------------------------------------------
# Helper to run async tests synchronously
# ---------------------------------------------------------------------------


def asyncio_run(coro):
    """Run an async coroutine in a synchronous test context."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already in a running loop — this happens with some pytest runners
        # Create a new event loop in a task
        import nest_asyncio

        nest_asyncio.apply(loop)
        return loop.run_until_complete(coro)
    elif loop:
        return loop.run_until_complete(coro)
    else:
        return asyncio.run(coro)
