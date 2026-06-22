"""
HashiCorp Vault KV v2 key store.

Uses the Vault Python SDK (``hvac``) to read/write API key secrets
under a configurable path.  Supports Kubernetes, AppRole, and token auth
methods.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any

import bcrypt

from .interface import KeyStoreInterface


class VaultKeyStore(KeyStoreInterface):
    """HashiCorp Vault KV v2 as the source of truth for API keys."""

    def __init__(
        self,
        addr: str,
        mount_path: str,
        auth_method: str = "kubernetes",
        role_id: str = "",
        secret_id: str = "",
        k8s_service_account: str = "/var/run/secrets/kubernetes.io/serviceaccount/token",
        k8s_review_path: str = "/kubernetes/review",
        redis_client=None,
        cache_ttl: int = 300,
        cache_jitter: int = 60,
    ) -> None:
        self._addr = addr.rstrip("/")
        self._mount_path = mount_path.rstrip("/")
        self._auth_method = auth_method

        # Lazy import — do not require hvault at import time
        import hvault

        self._client = hvault.Client(url=addr)
        self._authenticate_vault(auth_method, role_id, secret_id, k8s_service_account, k8s_review_path)

        # Wrap in cache
        self._wrapped: KeyStoreInterface
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
            with open(sa_path, "r") as f:
                jwt = f.read().strip()
            self._client.auth_kubernetes(
                role=os.environ.get("LLM_ROUTER_AUTH_VAULT_ROLE_ID", role_id),
                jwt=jwt,
                mount_point=review_path,
            )
        elif auth_method == "approle":
            self._client.auth_approle(
                role_id=os.environ.get("LLM_ROUTER_AUTH_VAULT_ROLE_ID", role_id),
                secret_id=os.environ.get("LLM_ROUTER_AUTH_VAULT_SECRET_ID", secret_id),
            )
        elif auth_method == "token":
            token = os.environ.get("LLM_ROUTER_AUTH_VAULT_TOKEN", "")
            if not token:
                raise RuntimeError("LLM_ROUTER_AUTH_VAULT_TOKEN is required for token auth")
            self._client.token = token
        else:
            raise ValueError(f"Unsupported Vault auth method: {auth_method}")

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
        return self._run_async(self._wrapped.get_key_by_hash(key_hash))

    # -- KeyStoreInterface forwarding -------------------------------
    async def get_key_by_hash(self, key_hash: str) -> dict | None:
        return await self._wrapped.get_key_by_hash(key_hash)

    async def get_key_by_id(self, key_id: str) -> dict | None:
        return await self._wrapped.get_key_by_id(key_id)

    async def create_key(self, record: dict) -> str:
        # The vault write goes directly to vault (backend), cache invalidated afterwards
        key_plain = record.pop("key_plain")
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
            "key_prefix": new_plain[:7],
            "created_at": now,
            "is_active": True,
            "grace_until": old.get("expires_at") or (now + grace_period),
        }
        await self.create_key(new_record)

        # Invalidate old
        self._client.write_secret(
            path=key_id,
            mount_point=self._mount_path,
            data={"data": {"is_active": False, "rotated_to": new_id}},
        )
        return new_plain

    async def delete_key(self, key_id: str) -> None:
        self._client.delete_secret(
            path=key_id,
            mount_point=self._mount_path,
        )

    async def list_keys(self) -> list[dict]:
        """List all keys under the mount path."""
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
                record = await self.get_key_by_id(kid)
                if record:
                    result.append({
                        "key_id": record["key_id"],
                        "key_prefix": record["key_prefix"],
                        "policy_name": record["policy_name"],
                        "is_active": record["is_active"],
                        "created_at": record["created_at"],
                        "expires_at": record.get("expires_at"),
                    })
            return result
        except Exception:
            return []

    async def update_last_used(self, key_id: str) -> None:
        """Update last_used_at for a key."""
        record = await self.get_key_by_id(key_id)
        if record:
            record["last_used_at"] = time.time()
            await self.create_key({**record, "key_plain": "placeholder"})  # placeholder

    def update_last_used_sync(self, key_id: str) -> None:
        """Sync version of update_last_used."""
        try:
            import asyncio
            asyncio.get_event_loop().create_task(self.update_last_used(key_id))
        except RuntimeError:
            pass
