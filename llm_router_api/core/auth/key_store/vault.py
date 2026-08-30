"""
HashiCorp Vault KV v2 key store.

Uses the official HashiCorp Vault Python client (``hvac``) to read/write API
key secrets under a configurable path.  Supports Kubernetes, AppRole, and
token auth methods.

Mount path convention
---------------------
``mount_path`` is the full KV v2 location, e.g.
``secret/data/llm-router/api-keys``.  The first segment (``secret``) is the
engine **mount point**; the remainder after ``data/`` is the **base path**
under the engine's ``data/`` directory.  ``hvac`` is called with
``mount_point="secret"`` and ``path="llm-router/api-keys/<key_id>"``.
"""

from __future__ import annotations

import os
import time
import uuid
import bcrypt

import logging

from typing import Any, Dict, List, Optional

from llm_router_api.core.auth.key_store.interface import KeyStoreInterface
from llm_router_api.core.auth.key_store._record_helpers import (
    apply_rate_limit_override,
    gen_key_prefix,
    gen_sha256_index,
)

_logger = logging.getLogger(__name__)


class VaultKeyStore(KeyStoreInterface):
    """
    HashiCorp Vault KV v2 as the source of truth for API keys.
    """

    def __init__(
        self,
        addr: str,
        mount_path: str,
        auth_method: str = "kubernetes",
        role_id: str = "",
        secret_id: str = "",
        k8s_service_account: str = (
            "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ),
        k8s_review_path: str = "/kubernetes/review",
        redis_client=None,
        cache_ttl: int = 300,
        cache_jitter: int = 60,
        _no_internal_cache=False,
    ) -> None:
        self._addr = addr.rstrip("/")
        self._mount_path = mount_path.rstrip("/")
        self._auth_method = auth_method
        # Optional Redis for the O(1) sha256 reverse index (shared with the cache)
        self._redis = redis_client

        # Lazy import — hvac is an optional dependency (llm-router[vault])
        import hvac

        self._client = hvac.Client(url=addr)
        self._authenticate_vault(
            auth_method, role_id, secret_id, k8s_service_account, k8s_review_path
        )

        # Wrap in cache (skip when create_key_store provides an external layer)
        self._wrapped: KeyStoreInterface
        if not _no_internal_cache:
            try:
                from .redis_cache import RedisKeyStoreCache

                self._wrapped = RedisKeyStoreCache(
                    backend=self,
                    redis_client=redis_client,
                    ttl=cache_ttl,
                    jitter=cache_jitter,
                )
            except Exception:
                self._wrapped = self  # fallback: no cache
        else:
            self._wrapped = self

    # ---- hvac path helpers -------------------------------------------------

    @property
    def _mount_point(self) -> str:
        """
        KV engine mount (e.g. ``secret`` from ``secret/data/llm-router/...``).
        """
        parts = self._mount_path.split("/")
        return parts[0]

    @property
    def _base_path(self) -> str:
        """
        Path under the engine's ``data/`` directory
        (e.g. ``llm-router/api-keys``), or ``""`` for the mount root.
        """
        parts = self._mount_path.split("/")
        if len(parts) > 2 and parts[1] == "data":
            return "/".join(parts[2:])
        return "/".join(parts[1:])

    def _secret_path(self, key_id: str) -> str:
        """
        Full ``hvac`` secret path for *key_id* (base path + key name).
        """
        base = self._base_path
        return f"{base}/{key_id}" if base else key_id

    def _read_record(self, key_id: str) -> Dict[str, Any]:
        """
        Read a key record from Vault KV v2 (raises on missing key).
        """
        secret_data = self._client.secrets.kv.v2.read_secret_version(
            path=self._secret_path(key_id),
            mount_point=self._mount_point,
        )
        return secret_data.get("data", {}).get("data", {}) or {}

    def _write_record(self, key_id: str, record: Dict[str, Any]) -> None:
        """
        Create or update a key record in Vault KV v2.
        """
        self._client.secrets.kv.v2.create_or_update_secret(
            path=self._secret_path(key_id),
            data=record,
            mount_point=self._mount_point,
        )

    def _list_key_names(self) -> List[str]:
        """
        List key names stored under the base path.
        """
        secret = self._client.secrets.kv.v2.list_secrets(
            path=self._base_path,
            mount_point=self._mount_point,
        )
        return (secret.get("data", {}) or {}).get("keys", []) or []

    def _delete_secret(self, key_id: str) -> None:
        """
        Delete the latest version of a key (raises on missing key).
        """
        self._client.secrets.kv.v2.delete_secret_version(
            path=self._secret_path(key_id),
            mount_point=self._mount_point,
        )

    @staticmethod
    def _is_not_found(exc: Exception) -> bool:
        """
        True when *exc* means "the secret does not exist" (HTTP 404).
        """
        try:
            import hvac

            if isinstance(exc, hvac.exceptions.InvalidPath):
                return True
        except ImportError:
            # intentional: hvac may be absent; fall back to the string check.
            pass
        text = str(exc)
        return "404" in text or "not found" in text.lower()

    # ---- authentication ------------------------------------------------------

    def _authenticate_vault(
        self,
        auth_method: str,
        role_id: str,
        secret_id: str,
        sa_path: str,
        review_path: str,
    ) -> None:
        """
        Authenticate to Vault using the selected method.
        """

        if auth_method == "kubernetes":
            with open(sa_path, "r", encoding="utf-8") as f:
                jwt = f.read().strip()
            self._client.auth.kubernetes.login(
                role=os.environ.get("LLM_ROUTER_AUTH_VAULT_ROLE_ID", role_id),
                jwt=jwt,
                mount_point=review_path,
            )
        elif auth_method == "approle":
            self._client.auth.approle.login(
                role_id=os.environ.get("LLM_ROUTER_AUTH_VAULT_ROLE_ID", role_id),
                secret_id=os.environ.get(
                    "LLM_ROUTER_AUTH_VAULT_SECRET_ID", secret_id
                ),
            )
        elif auth_method == "token":
            token = os.environ.get("LLM_ROUTER_AUTH_VAULT_TOKEN", "")
            if not token:
                raise RuntimeError(
                    "LLM_ROUTER_AUTH_VAULT_TOKEN is required for token auth"
                )
            self._client.token = token
        else:
            raise ValueError(f"Unsupported Vault auth method: {auth_method}")

    # -- sync wrappers (inherit _run_async from base class) ---------------
    def get_key_by_hash_sync(self, key_hash: str) -> Optional[dict]:
        return self._run_async(self._wrapped.get_key_by_hash(key_hash))

    def _index_key(self, key_index: str) -> str:
        """
        Redis reverse-index key: ``sha256(plaintext) -> key_id`` (O(1) lookup).
        """

        return f"auth:key:idx:{key_index}"

    async def get_key_by_plain(self, key_plain: str) -> Optional[dict]:
        """
        Look up a key record by its plaintext key using bcrypt.checkpw.

        Preferred path: O(1) via the ``sha256(plaintext) -> key_id`` reverse
        index in Redis (populated by :meth:`create_key`), verified with a
        single constant-time ``bcrypt.checkpw``.  Falls back to an O(n) scan
        of the Vault for legacy keys created before the index existed.

        .. note::
           Without the index (no Redis configured), each authentication
           triggers *one* ``list_secrets`` call plus one
           ``read_secret_version`` per Vault key until a match is found.
        """
        # O(1) index path (Redis available)
        if self._redis is not None:
            key_id = self._redis.get(self._index_key(gen_sha256_index(key_plain)))
            if key_id:
                record = await self.get_key_by_id(key_id)
                if record is not None:
                    stored_hash = record.get("key_hash")
                    if stored_hash and bcrypt.checkpw(
                        key_plain.encode(), stored_hash.encode()
                    ):
                        return record
                return None

        # Legacy fallback: full scan (constant-time bcrypt per key)
        try:
            keys = self._list_key_names()
        except Exception as exc:
            # If Vault is down we return None (the caller will reject the key)
            _logger.error("Vault list_secrets failed: %s", exc)
            return None

        # Warn when scanning many keys (indicates need for hash-based lookup)
        if len(keys) > 50:
            _logger.warning(
                "Vault scan of %d keys per plain-text auth check — "
                "consider using get_key_by_hash (cached) for better performance",
                len(keys),
            )

        for key_name in keys:
            try:
                record = self._read_record(key_name)
                stored_hash = record.get("key_hash")
                if stored_hash and bcrypt.checkpw(
                    key_plain.encode(), stored_hash.encode()
                ):
                    return {
                        "key_id": key_name,
                        "key_hash": stored_hash,
                        "key_plain": None,  # plaintext not available from Vault
                        "key_prefix": record.get("key_prefix", ""),
                        "policy_name": record.get("policy_name", "developer"),
                        "is_active": record.get("is_active", True),
                        "created_at": record.get("created_at"),
                        "expires_at": record.get("expires_at"),
                    }
            except Exception:
                continue
        return None

    def get_key_by_plain_sync(self, key_plain: str) -> Optional[dict]:
        """
        Synchronous version of :meth:`get_key_by_plain`.
        """

        return self._run_async(self.get_key_by_plain(key_plain))

    # -- KeyStoreInterface forwarding -------------------------------
    async def get_key_by_hash(self, key_hash: str) -> Optional[dict]:
        # Forward to cache when available; fall back to full scan for direct use
        if self._wrapped is not self:
            return await self._wrapped.get_key_by_hash(key_hash)
        # Direct path (when _no_internal_cache=True): scan all keys and compare hash
        try:
            keys = self._list_key_names()
        except Exception:
            return None

        for key_name in keys:
            try:
                record = self._read_record(key_name)
                stored_hash = record.get("key_hash")
                if stored_hash and stored_hash == key_hash:
                    return {
                        "key_id": key_name,
                        "key_hash": stored_hash,
                        "key_plain": None,
                        "key_prefix": record.get("key_prefix", ""),
                        "policy_name": record.get("policy_name", "developer"),
                        "is_active": record.get("is_active", True),
                        "created_at": record.get("created_at"),
                        "expires_at": record.get("expires_at"),
                    }
            except Exception:
                continue
        return None

    async def get_key_by_id(self, key_id: str) -> Optional[dict]:
        # Forward to cache when available; fall back to direct read for direct use
        if self._wrapped is not self:
            return await self._wrapped.get_key_by_id(key_id)
        # Direct path (when _no_internal_cache=True): read from Vault directly
        try:
            record = self._read_record(key_id)
        except Exception:
            return None
        if not record.get("is_active"):
            return None
        return {
            "key_id": key_id,
            "key_hash": record.get("key_hash"),
            "key_plain": None,
            "key_prefix": record.get("key_prefix", ""),
            "policy_name": record.get("policy_name", "developer"),
            "is_active": record.get("is_active", True),
            "created_at": record.get("created_at"),
            "expires_at": record.get("expires_at"),
        }

    async def create_key(self, record: dict) -> str:
        # The vault write goes directly to vault (backend), cache invalidated afterwards
        record = dict(record)  # prevent mutating caller's dict
        key_plain = record.pop("key_plain")
        key_hash = bcrypt.hashpw(key_plain.encode(), bcrypt.gensalt()).decode()
        key_index = gen_sha256_index(key_plain)

        key_id = record.get("key_id", f"key-{uuid.uuid4().hex[:8]}")
        now = time.time()
        api_record = {
            "key_id": key_id,
            "key_hash": key_hash,
            "key_index": key_index,
            "key_prefix": gen_key_prefix(key_plain),
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

        # Write to Vault KV v2 (hvac wraps the record in the "data" field)
        self._write_record(key_id, api_record)
        # O(1) reverse index (best-effort — the scan fallback still works)
        if self._redis is not None:
            self._redis.set(self._index_key(key_index), key_id)
        return key_plain

    async def rotate_key(self, key_id: str, grace_period: int) -> str:
        old = await self.get_key_by_id(key_id)
        if old is None:
            raise ValueError(f"Key {key_id} not found in Vault")

        new_plain = f"{old['key_prefix']}{uuid.uuid4().hex[:40]}"
        new_id = f"{key_id}-rotated-{int(time.time())}"
        now = time.time()

        new_record = {
            **old,
            "key_id": new_id,
            "key_plain": new_plain,
            "key_prefix": gen_key_prefix(new_plain),
            "created_at": now,
            "is_active": True,
            "grace_until": old.get("expires_at") or (now + grace_period),
        }
        new_record.pop("key_hash", None)  # create_key re-hashes from key_plain
        # create_key stores the new O(1) index and writes the record
        await self.create_key(new_record)
        # Retire the old key's index so the old plaintext stops resolving
        old_index = old.get("key_index")
        if self._redis is not None and old_index:
            self._redis.delete(self._index_key(old_index))

        # Ensure grace_until is persisted (create_key always writes grace_until:
        # None, override it)
        await self.update_grace_until(new_id, new_record["grace_until"])

        # Invalidate old
        self._write_record(key_id, {"is_active": False, "rotated_to": new_id})
        return new_plain

    async def disable_key(self, key_id: str) -> None:
        """
        Deactivate a key by setting is_active=False.
        """
        try:
            record = self._read_record(key_id)
        except Exception:
            raise ValueError(f"Key {key_id} not found") from None
        old_index = record.get("key_index")
        record["is_active"] = False
        self._write_record(key_id, record)
        # Retire the index so the disabled key can't authenticate
        if self._redis is not None and old_index:
            self._redis.delete(self._index_key(old_index))

    async def enable_key(self, key_id: str) -> None:
        """
        Re-activate a previously deactivated key.
        """
        try:
            record = self._read_record(key_id)
        except Exception:
            raise ValueError(f"Key {key_id} not found") from None
        index = record.get("key_index")
        record["is_active"] = True
        self._write_record(key_id, record)
        # Re-add the index so the re-enabled key can authenticate again
        if self._redis is not None and index:
            self._redis.set(self._index_key(index), key_id)

    async def update_policy_override(
        self, key_id: str, rate_limit: Optional[int]
    ) -> None:
        """
        Set or clear the ``rate_limit`` policy override (see interface).
        """
        try:
            record = self._read_record(key_id)
        except Exception:
            raise ValueError(f"Key {key_id} not found") from None
        record = apply_rate_limit_override(record, rate_limit)
        self._write_record(key_id, record)

    async def delete_key(self, key_id: str) -> None:
        """
        Delete key from Vault.

        Only "not found" / 404 errors are silently ignored (key may have been
        deleted externally).  Network or authentication errors propagate to the
        caller so that failures are not masked.
        """
        # Best-effort index removal (record may already be inactive/absent)
        if self._redis is not None:
            old = await self._wrapped.get_key_by_id(key_id)
            old_index = (old or {}).get("key_index")
            if old_index:
                self._redis.delete(self._index_key(old_index))
        try:
            self._delete_secret(key_id)
        except Exception as exc:
            # Treat HTTP 404 as "key already gone" — no-op
            if self._is_not_found(exc):
                return
            raise

    async def list_keys(self) -> List[dict]:
        """
        List all keys under the mount path, including disabled ones.
        """

        try:
            keys = self._list_key_names()
            # Strip trailing slashes from key names
            keys = [k.rstrip("/") for k in keys if k.strip()]
            result = []
            for kid in keys:
                try:
                    record = self._read_record(kid)
                except Exception:
                    continue
                result.append(
                    {
                        "key_id": kid,
                        "key_prefix": record.get("key_prefix", ""),
                        "policy_name": record.get("policy_name", "developer"),
                        "is_active": record.get("is_active", True),
                        "created_at": record.get("created_at"),
                        "expires_at": record.get("expires_at"),
                    }
                )
            return result
        except Exception:
            return []

    async def update_last_used(self, key_id: str) -> None:
        """
        Update last_used_at for a key via targeted write — never re-hashes.
        """
        try:
            record = self._read_record(key_id)
        except Exception:  # key not found — fire-and-forget semantics
            return
        record["last_used_at"] = time.time()
        self._write_record(key_id, record)

    def update_last_used_sync(self, key_id: str) -> None:
        """
        Sync version of :meth:`update_last_used`.

        .. note::
           Fire-and-forget — the task may be dropped if the event loop
           closes before it runs (lost update).  Prefer :meth:`update_last_used`
           when possible.
        """
        try:
            import asyncio

            asyncio.get_event_loop().create_task(self.update_last_used(key_id))
        except RuntimeError:
            # intentional: no running event loop — best-effort, skip scheduling.
            pass

    async def update_grace_until(self, key_id: str, grace_until: float) -> None:
        """
        Update grace_until for a key (read-modify-write to preserve the record).
        """
        try:
            record = self._read_record(key_id)
        except Exception:
            return
        record["grace_until"] = grace_until
        self._write_record(key_id, record)
