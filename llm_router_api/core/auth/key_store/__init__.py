"""
Key store factory — selects the concrete backend based on ``store_type``.
"""

from __future__ import annotations

import os
import random

from .interface import KeyStoreInterface
from .memory import MemoryKeyStore

# Lazy imports to avoid hard dependency on hvault/bcrypt at import time
_VAULT_AVAILABLE = False
_REDIS_AVAILABLE = False
try:
    import redis  # noqa: F401

    _REDIS_AVAILABLE = True
except ImportError:
    pass

try:
    import hvault  # noqa: F401

    _VAULT_AVAILABLE = True
except ImportError:
    pass


def _make_shared_redis_client(kwargs: dict) -> redis.Redis | None:
    """Return a single ``redis.Redis`` instance shared between store and cache.

    Prefer an explicitly passed ``redis_client`` from *kwargs*; otherwise build
    one from the standard ``redis_host/port/db/password`` kwargs so that both
    :class:`RedisKeyStore` and :class:`RedisKeyStoreCache` reuse the **same**
    connection pool (cache doesn't silently fall back to *no-op* when
    ``redis_client is None``).
    """
    client = kwargs.get("redis_client")
    if client is not None:
        return client
    host = kwargs.get("redis_host") or "127.0.0.1"
    port = int(kwargs.get("redis_port", 6379))
    db = int(kwargs.get("redis_db", 0))
    password = kwargs.get("redis_password")
    return redis.Redis(
        host=host,
        port=port,
        db=db,
        decode_responses=True,
        password=password,
    )


def create_key_store(
    store_type: str = "memory",
    **kwargs,
) -> KeyStoreInterface:
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
    KeyStoreInterface
        A configured key store (wrapped in a Redis cache layer when
        ``LLM_ROUTER_AUTH_KEY_CACHE_TTL`` is set).
    """
    # Create ONE shared redis client for both store and cache
    shared_client = _make_shared_redis_client(kwargs)

    if store_type == "vault":
        if not _VAULT_AVAILABLE:
            raise RuntimeError(
                "hashicorp-vault is not installed. Install it with: "
                "pip install llm-router[vault]"
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
        # seed file from env (read here so the env var is discovered)
        seed_file = os.environ.get("LLM_ROUTER_AUTH_MEMORY_SEED_FILE")
        store = MemoryKeyStore(seed_file=seed_file)

    else:
        raise ValueError(f"Unknown auth key store type: {store_type}")

    # Wrap with Redis cache when cache TTL is configured
    cache_ttl = os.environ.get("LLM_ROUTER_AUTH_KEY_CACHE_TTL", "0")
    cache_jitter = os.environ.get("LLM_ROUTER_AUTH_KEY_CACHE_JITTER", "0")
    if cache_ttl and int(cache_ttl) > 0:
        from .redis_cache import RedisKeyStoreCache

        ttl = int(cache_ttl) + random.randint(0, int(cache_jitter or "0"))
        store = RedisKeyStoreCache(store, redis_client=shared_client, ttl=ttl)

    return store


__all__ = ["create_key_store"]
