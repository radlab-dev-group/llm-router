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

from llm_router_api.core.auth.key_store.interface import KeyStoreInterface
from llm_router_api.core.auth.key_store._record_helpers import gen_key_prefix


class VaultKeyStore(KeyStoreInterface):
    """HashiCorp Vault KV v2 as the source of truth for API keys."""

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
        """Authenticate to Vault using the selected method."""
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
    def get_key_by_hash_sync(self, key_hash: str) -> dict | None:
        return self._run_async(self._wrapped.get_key_by_hash(key_hash))

    async def get_key_by_plain(self, key_plain: str) -> dict | None:
        """Look up a key record by its plaintext key using bcrypt.checkpw.

        Scans all keys in Vault since hashes are stored with random salts
        and cannot be looked up by hash directly.
        """
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

    def get_key_by_plain_sync(self, key_plain: str) -> dict | None:
        """Synchronous version of :meth:`get_key_by_plain`."""
        return self._run_async(self.get_key_by_plain(key_plain))

    # -- KeyStoreInterface forwarding -------------------------------
    async def get_key_by_hash(self, key_hash: str) -> dict | None:
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

    async def get_key_by_id(self, key_id: str) -> dict | None:
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

        key_id = record.get("key_id", f"key-{uuid.uuid4().hex[:8]}")
        now = time.time()
        api_record = {
            "key_id": key_id,
            "key_hash": key_hash,
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
        return key_plain

    async def rotate_key(self, key_id: str, grace_period: int) -> str:
        old = await self.get_key_by_id(key_id)
        if old is None:
            raise ValueError(f"Key {key_id} not found in Vault")

        new_plain = f"{old['key_prefix']}{uuid.uuid4().hex[:40]}"
        new_hash = bcrypt.hashpw(new_plain.encode(), bcrypt.gensalt()).decode()
        new_id = f"{key_id}-rotated-{int(time.time())}"
        now = time.time()

        new_record = {
            **old,
            "key_id": new_id,
            "key_hash": new_hash,
            "key_plain": new_plain,
            "key_prefix": gen_key_prefix(new_plain),
            "created_at": now,
            "is_active": True,
            "grace_until": old.get("expires_at") or (now + grace_period),
        }
        await self.create_key(new_record)

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
        """Deactivate a key by setting is_active=False."""
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
        record["is_active"] = False
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": record},
        )

    async def enable_key(self, key_id: str) -> None:
        """Re-activate a previously deactivated key."""
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
        record["is_active"] = True
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": record},
        )

    async def delete_key(self, key_id: str) -> None:
        try:
            self._client.delete_secret(
                path=key_id,
                mount_point=self._mount_path,
            )
        except Exception:  # key may not exist — treat as no-op
            pass

    async def list_keys(self) -> list[dict]:
        """List all keys under the mount path, including disabled ones."""
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
        """Update last_used_at for a key."""
        record = await self.get_key_by_id(key_id)
        if record:
            record["last_used_at"] = time.time()
            await self.create_key(
                {**record, "key_plain": "placeholder"}
            )  # placeholder

    def update_last_used_sync(self, key_id: str) -> None:
        """Sync version of :meth:`update_last_used`.

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
        """Update grace_until for a key (read-modify-write to preserve the record)."""
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
