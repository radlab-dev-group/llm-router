"""
HashiCorp Vault KV v2 key store.

Uses the Vault Python SDK (``hvac``) to read/write API key secrets
under a configurable path.  Supports Kubernetes, AppRole, and token auth
methods.
"""

from __future__ import annotations

import os
import time
import uuid
import bcrypt

import logging

from typing import List, Optional

from llm_router_api.core.auth.key_store.interface import KeyStoreInterface
from llm_router_api.core.auth.key_store._record_helpers import (
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

        # Lazy import — do not require hvault at import time
        import hvault

        self._client = hvault.Client(url=addr)
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
            self._client.auth_kubernetes(
                role=os.environ.get("LLM_ROUTER_AUTH_VAULT_ROLE_ID", role_id),
                jwt=jwt,
                mount_point=review_path,
            )
        elif auth_method == "approle":
            self._client.auth_approle(
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
        kv_path = self._mount_path.rstrip("/")
        try:
            secret = self._client.secrets.kv.v2.list_secrets(
                path=kv_path,
                mount_point=kv_path.split("/")[0] if "/" in kv_path else None,
            )
        except Exception as exc:
            # If Vault is down we return None (the caller will reject the key)
            _logger.error("Vault list_secrets failed: %s", exc)
            return None

        secrets_data = secret.get("data", {}) or {}
        keys = secrets_data.get("keys") or []

        # Warn when scanning many keys (indicates need for hash-based lookup)
        if len(keys) > 50:
            _logger.warning(
                "Vault scan of %d keys per plain-text auth check — "
                "consider using get_key_by_hash (cached) for better performance",
                len(keys),
            )

        for key_name in keys:
            try:
                secret_data = self._client.secrets.kv.v2.read_secret_version(
                    path=f"{kv_path}/{key_name}",
                    mount_point=kv_path.split("/")[0] if "/" in kv_path else None,
                )
                record = secret_data.get("data", {}).get("data", {}) or {}
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
        kv_path = self._mount_path.rstrip("/")
        try:
            secret = self._client.secrets.kv.v2.list_secrets(
                path=kv_path,
                mount_point=kv_path.split("/")[0] if "/" in kv_path else None,
            )
        except Exception:
            return None

        secrets_data = secret.get("data", {}) or {}
        keys = secrets_data.get("keys") or []

        for key_name in keys:
            try:
                secret_data = self._client.secrets.kv.v2.read_secret_version(
                    path=f"{kv_path}/{key_name}",
                    mount_point=kv_path.split("/")[0] if "/" in kv_path else None,
                )
                record = secret_data.get("data", {}).get("data", {}) or {}
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
        kv_path = f"{self._mount_path.rstrip('/')}/{key_id}"
        try:
            secret_data = self._client.secrets.kv.v2.read_secret_version(
                path=kv_path,
                mount_point=(
                    self._mount_path.split("/")[0]
                    if "/" in self._mount_path
                    else None
                ),
            )
            record = secret_data.get("data", {}).get("data", {}) or {}
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
        except Exception:
            return None

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

        # Write to Vault KV v2 (data field for KV v2)
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": api_record},
        )
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
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": {"is_active": False, "rotated_to": new_id}},
        )
        return new_plain

    async def disable_key(self, key_id: str) -> None:
        """
        Deactivate a key by setting is_active=False.
        """

        kv_path = f"{self._mount_path.rstrip('/')}/{key_id}"
        try:
            secret_data = self._client.secrets.kv.v2.read_secret_version(
                path=kv_path,
                mount_point=(
                    self._mount_path.split("/")[0]
                    if "/" in self._mount_path
                    else None
                ),
            )
            record = secret_data.get("data", {}).get("data", {}) or {}
        except Exception:
            raise ValueError(f"Key {key_id} not found") from None
        old_index = record.get("key_index")
        record["is_active"] = False
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": record},
        )
        # Retire the index so the disabled key can't authenticate
        if self._redis is not None and old_index:
            self._redis.delete(self._index_key(old_index))

    async def enable_key(self, key_id: str) -> None:
        """
        Re-activate a previously deactivated key.
        """

        kv_path = f"{self._mount_path.rstrip('/')}/{key_id}"
        try:
            secret_data = self._client.secrets.kv.v2.read_secret_version(
                path=kv_path,
                mount_point=(
                    self._mount_path.split("/")[0]
                    if "/" in self._mount_path
                    else None
                ),
            )
            record = secret_data.get("data", {}).get("data", {}) or {}
        except Exception:
            raise ValueError(f"Key {key_id} not found") from None
        index = record.get("key_index")
        record["is_active"] = True
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": record},
        )
        # Re-add the index so the re-enabled key can authenticate again
        if self._redis is not None and index:
            self._redis.set(self._index_key(index), key_id)

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
            self._client.delete_secret(
                path=key_id,
                mount_point=self._mount_path,
            )
        except Exception as exc:
            # Treat HTTP 404 as "key already gone" — no-op
            if "404" in str(exc) or "not found" in str(exc).lower():
                return
            raise

    async def list_keys(self) -> List[dict]:
        """
        List all keys under the mount path, including disabled ones.
        """

        try:
            response = self._client.list_secret(
                path=self._mount_path.rstrip("/"),
            )
            if not response or not response.get("data"):
                return []
            keys = response["data"].get("keys", [])
            # Strip trailing slashes from key names
            keys = [k.rstrip("/") for k in keys if k.strip()]
            result = []
            for kid in keys:
                kv_path = f"{self._mount_path.rstrip('/')}/{kid}"
                try:
                    secret_data = self._client.secrets.kv.v2.read_secret_version(
                        path=kv_path,
                        mount_point=(
                            self._mount_path.split("/")[0]
                            if "/" in self._mount_path
                            else None
                        ),
                    )
                    record = secret_data.get("data", {}).get("data", {}) or {}
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

        kv_path = f"{self._mount_path.rstrip('/')}/{key_id}"
        try:
            secret_data = self._client.secrets.kv.v2.read_secret_version(
                path=kv_path,
                mount_point=(
                    self._mount_path.split("/")[0]
                    if "/" in self._mount_path
                    else None
                ),
            )
            record = secret_data.get("data", {}).get("data", {}) or {}
        except Exception:  # key not found — fire-and-forget semantics
            return
        record["last_used_at"] = time.time()
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": record},
        )

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
            pass

    async def update_grace_until(self, key_id: str, grace_until: float) -> None:
        """
        Update grace_until for a key (read-modify-write to preserve the record).
        """

        kv_path = f"{self._mount_path.rstrip('/')}/{key_id}"
        try:
            secret_data = self._client.secrets.kv.v2.read_secret_version(
                path=kv_path,
                mount_point=(
                    self._mount_path.split("/")[0]
                    if "/" in self._mount_path
                    else None
                ),
            )
            record = secret_data.get("data", {}).get("data", {}) or {}
        except Exception:
            return
        record["grace_until"] = grace_until
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": record},
        )
