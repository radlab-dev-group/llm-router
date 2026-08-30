"""
Key store factory — selects the concrete backend based on ``store_type``.
"""

from __future__ import annotations

import os
import secrets

from typing import Optional, Tuple

from llm_router_api.base.constants import LLM_ROUTER_AUTH_REDIS_PROTOCOL
from llm_router_api.core.auth.key_store.memory import MemoryKeyStore
from llm_router_api.core.auth.key_store.interface import KeyStoreInterface

# Lazy imports to avoid hard dependency on hvac/bcrypt at import time
_VAULT_AVAILABLE = False
_REDIS_AVAILABLE = False
try:
    import redis  # noqa: F401

    _REDIS_AVAILABLE = True
except ImportError:
    # intentional: redis is optional — flag stays False when not installed.
    pass

try:
    import hvac  # noqa: F401

    _VAULT_AVAILABLE = True
except ImportError:
    # intentional: hvac is optional — flag stays False when not installed.
    pass


def _make_shared_redis_client(kwargs: dict) -> Optional[redis.Redis]:
    """
    Return a single ``redis.Redis`` instance shared between store and cache.

    Prefer an explicitly passed ``redis_client`` from *kwargs*; otherwise build
    one from the standard ``redis_host/port/db/password`` kwargs so that both
    :class:`RedisKeyStore` and :class:`RedisKeyStoreCache` reuse the **same**
    connection pool (cache doesn't silently fall back to *no-op* when
    ``redis_client is None``).

    When a client is built from kwargs, verifies connectivity with ``PING``.
    A RuntimeError is raised if Redis refuses the connection so that
    startup failure is immediate rather than surfacing on the first request.
    """
    client = kwargs.get("redis_client")
    if client is not None:
        return client
    host = kwargs.get("redis_host") or "127.0.0.1"
    port = int(kwargs.get("redis_port", 6379))
    db = int(kwargs.get("redis_db", 0))
    password = kwargs.get("redis_password")
    protocol = int(kwargs.get("redis_protocol") or LLM_ROUTER_AUTH_REDIS_PROTOCOL)
    client = redis.Redis(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
        password=password,
        protocol=protocol,
    )
    # Verify connectivity: redis.Redis() is lazy — the first real operation
    # (ping) is what actually opens the TCP connection.
    try:
        client.ping()
    except redis.ConnectionError as exc:
        raise ConnectionError(
            f"Auth key-store Redis is unreachable at {host}:{port} "
            f"(db={db}): {exc}"
        ) from exc
    return client


def create_key_store(
    store_type: str = "memory",
    **kwargs,
) -> Tuple[KeyStoreInterface, Optional[redis.Redis]]:
    """
    Create a key store instance.

    Parameters
    ----------
    store_type : str
        One of ``"vault"``, ``"redis"``, ``"memory"``.
    **kwargs
        Backend-specific parameters forwarded to the constructor.

    Returns
    -------
    Tuple[KeyStoreInterface, Optional[redis.Redis]]
        ``(store, shared_client)`` — the key store and the verified Redis
        client (``None`` for in-memory stores).  ``shared_client`` is useful
        for callers that need a ready-to-use Redis connection (rate limiter,
        cache wrapper, etc.).
    """
    # Create ONE shared redis client for both store and cache — only when a
    # Redis-backed store is requested.  Memory stores never touch Redis.
    if store_type in ("redis", "vault"):
        shared_client = _make_shared_redis_client(kwargs)
    else:
        shared_client = None

    if store_type == "vault":
        if not _VAULT_AVAILABLE:
            raise RuntimeError(
                "hvac is not installed. Install it with: "
                "pip install llm-router[vault] (or: pip install hvac)"
            )
        from .vault import VaultKeyStore

        kwargs["redis_client"] = shared_client
        kwargs["_no_internal_cache"] = True  # external cache (below) handles caching
        store: KeyStoreInterface = VaultKeyStore(**kwargs)

    elif store_type == "redis":
        if not _REDIS_AVAILABLE:
            raise RuntimeError(
                "redis is not installed. Install it with: pip install redis"
            )
        from .redis_store import RedisKeyStore

        kwargs["redis_client"] = shared_client
        store = RedisKeyStore(**kwargs)

    elif store_type == "memory":
        from llm_router_api.base.constants import LLM_ROUTER_AUTH_MEMORY_SEED_FILE

        store = MemoryKeyStore(seed_file=LLM_ROUTER_AUTH_MEMORY_SEED_FILE)
        shared_client = None  # memory store does not use Redis

    else:
        raise ValueError(f"Unknown auth key store type: {store_type}")

    # Wrap with Redis cache when cache TTL is configured
    cache_ttl = os.environ.get("LLM_ROUTER_AUTH_KEY_CACHE_TTL", "0")
    cache_jitter = os.environ.get("LLM_ROUTER_AUTH_KEY_CACHE_JITTER", "0")
    if cache_ttl and int(cache_ttl) > 0:
        from .redis_cache import RedisKeyStoreCache

        ttl = int(cache_ttl) + secrets.randbelow(int(cache_jitter or "0") + 1)
        store = RedisKeyStoreCache(store, redis_client=shared_client, ttl=ttl)

    return store, shared_client


__all__ = ["create_key_store"]
