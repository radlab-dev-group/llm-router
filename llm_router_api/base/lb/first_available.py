"""
Implementation of a *first‑available* provider selection strategy that coordinates
access across multiple processes using Redis.  The code is split into small,
focused classes to improve readability, testability and maintainability.

Typical usage
-------------

>>> strategy = FirstAvailableStrategy(models_config_path='dir/models-config.json')
>>> provider = strategy.get_provider('my-model', providers)
>>> # … use the provider …
>>> strategy.put_provider('my-model', provider)

The public API is provided by :class:`FirstAvailableStrategy`.  Internally the
strategy delegates the low‑level Redis operations to :class:`RedisLockManager`
and the monitoring of provider health to :class:`ProviderMonitorWrapper`.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Optional Redis import – the strategy raises a clear error if Redis is not
# available at runtime.
# --------------------------------------------------------------------------- #
try:
    import redis

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False

from llm_router_api.base.constants import REDIS_HOST, REDIS_PORT
from llm_router_api.base.lb.provider_monitor import RedisProviderMonitor
from llm_router_api.base.lb.strategy import ChooseProviderStrategyI


# --------------------------------------------------------------------------- #
# Helper class – low‑level Redis lock handling
# --------------------------------------------------------------------------- #
class RedisLockManager:
    """
    Encapsulates all Redis‑based locking primitives used by the strategy.

    The manager registers four Lua scripts:

    * ``_acquire_script`` – atomically acquire a provider lock.
    * ``_release_script`` – release a provider lock.
    * ``_acquire_host_script`` – acquire a host‑wide lock (only one provider per
      host may be active at a time).
    * ``_release_host_script`` – release a host lock.

    All scripts work on simple string values (``'true'`` = locked,
    ``'false'`` = free).  Missing fields are treated as free.
    """

    def __init__(self, client: redis.Redis) -> None:
        """
        Parameters
        ----------
        client:
            An instantiated :class:`redis.Redis` connection with
            ``decode_responses=True``.
        """
        self.client = client
        self._register_scripts()

    # ------------------------------------------------------------------- #
    # Lua script registration
    # ------------------------------------------------------------------- #
    def _register_scripts(self) -> None:
        """Register the four Lua scripts used for locking."""
        # Provider acquire – treat missing or "false" as free
        self.acquire_script = self.client.register_script(
            """
            local redis_key = KEYS[1]
            local field = ARGV[1]
            local v = redis.call('HGET', redis_key, field)
            if v == false or v == 'false' then
                redis.call('HSET', redis_key, field, 'true')
                return 1
            end
            return 0
            """
        )
        # Provider release – delete the field
        self.release_script = self.client.register_script(
            """
            local redis_key = KEYS[1]
            local field = ARGV[1]
            redis.call('HDEL', redis_key, field)
            return 1
            """
        )
        # Host acquire – a simple key, not a hash
        self.acquire_host_script = self.client.register_script(
            """
            local host_key = KEYS[1]
            local v = redis.call('GET', host_key)
            if v == false or v == 'false' then
                redis.call('SET', host_key, 'true')
                return 1
            end
            return 0
            """
        )
        # Host release – delete the key
        self.release_host_script = self.client.register_script(
            """
            local host_key = KEYS[1]
            redis.call('DEL', host_key)
            return 1
            """
        )

    # ------------------------------------------------------------------- #
    # Public locking helpers
    # ------------------------------------------------------------------- #
    def acquire_provider(self, redis_key: str, field: str) -> bool:
        """
        Try to lock a provider.

        Returns ``True`` if the lock was obtained, ``False`` otherwise.
        """
        result = int(self.acquire_script(keys=[redis_key], args=[field]))
        return result == 1

    def release_provider(self, redis_key: str, field: str) -> None:
        """Release a previously acquired provider lock."""
        self.release_script(keys=[redis_key], args=[field])

    def acquire_host(self, host_key: str) -> bool:
        """
        Acquire a lock that guarantees only one provider on the given host
        is active at a time.
        """
        result = int(self.acquire_host_script(keys=[host_key], args=[]))
        return result == 1

    def release_host(self, host_key: str) -> None:
        """Release a host‑wide lock."""
        self.release_host_script(keys=[host_key], args=[])


# --------------------------------------------------------------------------- #
# Wrapper around the existing RedisProviderMonitor
# --------------------------------------------------------------------------- #
class ProviderMonitorWrapper:
    """
    Thin wrapper around
    :class:`llm_router_api.base.lb.provider_monitor.RedisProviderMonitor`
    that isolates the strategy from the concrete monitor implementation.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        check_interval: int = 30,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._monitor = RedisProviderMonitor(
            redis_client=redis_client,
            check_interval=check_interval,
            clear_buffers=clear_buffers,
            logger=logger,
        )

    # ------------------------------------------------------------------- #
    # Delegated methods
    # ------------------------------------------------------------------- #
    def add_providers(self, model_name: str, providers: List[Dict]) -> None:
        """Register a list of providers for a given model."""
        self._monitor.add_providers(model_name, providers)

    def get_providers(
        self, model_name: str, only_active: bool = False
    ) -> List[Dict]:
        """
        Retrieve the provider list for *model_name*.

        Parameters
        ----------
        only_active:
            If ``True`` return only providers that are currently considered
            healthy/active by the monitor.
        """
        return self._monitor.get_providers(
            model_name=model_name, only_active=only_active
        )


# --------------------------------------------------------------------------- #
# Main strategy class – public entry point
# --------------------------------------------------------------------------- #
class FirstAvailableStrategy(ChooseProviderStrategyI):
    """
    Strategy that selects the first free provider for a model using Redis‑based
    coordination.

    The class implements the abstract :class:`ChooseProviderStrategyI` interface
    and adds the following responsibilities:

    * **Provider locking** – ensures that at most one worker holds a particular
      provider at any time, even across different hosts.
    * **Host‑level locking** – guarantees that a single host never serves more
      than one provider concurrently (optional, based on the provider payload).
    * **Health monitoring** – delegates to :class:`ProviderMonitorWrapper` to
      keep the list of active providers up‑to‑date.
    """

    # ------------------------------------------------------------------- #
    # Construction
    # ------------------------------------------------------------------- #
    def __init__(
        self,
        models_config_path: str,
        redis_host: str = REDIS_HOST,
        redis_port: int = REDIS_PORT,
        redis_db: int = 0,
        timeout: int = 60,
        check_interval: float = 0.1,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Parameters
        ----------
        models_config_path:
            Path to the JSON file that contains model‑to‑provider mappings.
        redis_host, redis_port, redis_db:
            Connection details for the Redis server.
        timeout:
            Maximum number of seconds to wait for a free provider before raising
            :class:`TimeoutError`.
        check_interval:
            Sleep interval (seconds) between successive attempts to acquire a
            provider.
        clear_buffers:
            If ``True`` the Redis state is cleared at start‑up, ensuring a clean
            slate.
        logger:
            Optional custom logger.  If omitted a module‑level logger is used.
        """
        if not _REDIS_AVAILABLE:  # pragma: no cover
            raise RuntimeError(
                "Redis is not installed. Install the `redis` package to use "
                "FirstAvailableStrategy."
            )

        super().__init__(models_config_path=models_config_path, logger=logger)

        # -----------------------------------------------------------------
        # Redis client & helper objects
        # -----------------------------------------------------------------
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
        )
        self.lock_manager = RedisLockManager(self.redis_client)
        self.monitor = ProviderMonitorWrapper(
            redis_client=self.redis_client,
            check_interval=30,
            clear_buffers=clear_buffers,
            logger=self.logger,
        )

        # -----------------------------------------------------------------
        # Configuration
        # -----------------------------------------------------------------
        self.timeout = timeout
        self.check_interval = check_interval

        if clear_buffers:
            self._clear_buffers()

    # ------------------------------------------------------------------- #
    # Public API – provider acquisition / release
    # ------------------------------------------------------------------- #
    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict]:
        """
        Acquire a provider for *model_name*.

        The method now remembers the last host that successfully served the
        model.  On subsequent calls it first tries to reuse that host if it is
        still available and healthy.
        """
        if not providers:
            return None

        # Register providers for health monitoring (idempotent)
        self.monitor.add_providers(model_name, providers)

        redis_key = self._redis_key(model_name)

        # Ensure the hash and its fields exist – idempotent initialisation
        if not self.redis_client.exists(redis_key):
            for p in providers:
                self.redis_client.hset(redis_key, self._provider_field(p), "false")

        # --------------------------------------------------------------
        # Try to reuse the last host that served this model
        # --------------------------------------------------------------
        last_host = self._get_last_host(redis_key)
        if last_host:
            # Find a provider that matches the stored host name
            candidate = next(
                (
                    p
                    for p in providers
                    if p.get("host") == last_host or p.get("server") == last_host
                ),
                None,
            )
            if candidate:
                # Verify that the candidate is still considered active
                active = self.monitor.get_providers(
                    model_name=model_name, only_active=True
                )
                if candidate in active:
                    field = self._provider_field(candidate)
                    if self.lock_manager.acquire_provider(redis_key, field):
                        if self._acquire_host_if_needed(candidate):
                            candidate["__chosen_field"] = field
                            # Remember this host for the next call
                            self._set_last_host(redis_key, last_host)
                            return candidate
                        # Host lock failed – release provider lock
                        self.lock_manager.release_provider(redis_key, field)

        is_random = bool(options and options.get("random_choice", False))

        start = time.time()
        while True:
            active = self.monitor.get_providers(
                model_name=model_name, only_active=True
            )
            if not active:
                # No active providers – wait a bit and retry
                time.sleep(self.check_interval)

            if time.time() - start > self.timeout:
                raise TimeoutError(
                    f"No available provider for model '{model_name}' after "
                    f"{self.timeout} seconds."
                )

            if is_random:
                chosen = self._try_acquire_random(redis_key, active)
                if chosen:
                    # Remember the host that just served the model
                    host_name = chosen.get("host") or chosen.get("server")
                    if host_name:
                        self._set_last_host(redis_key, host_name)
                    return chosen
            else:
                chosen = self._try_acquire_deterministic(redis_key, active)
                if chosen:
                    host_name = chosen.get("host") or chosen.get("server")
                    if host_name:
                        self._set_last_host(redis_key, host_name)
                    return chosen

            # Back‑off before the next attempt
            time.sleep(self.check_interval)

    def put_provider(
        self,
        model_name: str,
        provider: Dict,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Release a previously acquired *provider*.

        The method removes the provider lock from Redis and, if a host lock was
        obtained, releases that as well.  Temporary helper fields (``__chosen_field``,
        ``__host_key``) are stripped from the dictionary.
        """
        redis_key = self._redis_key(model_name)
        field = self._provider_field(provider)

        # Release provider lock
        self.lock_manager.release_provider(redis_key, field)

        # Release host lock if it exists
        host_key = provider.get("__host_key")
        if host_key:
            self.lock_manager.release_host(host_key)

        # Clean helper entries from the caller‑provided dict
        provider.pop("__chosen_field", None)
        provider.pop("__host_key", None)

    # ------------------------------------------------------------------- #
    # Private helper methods
    # ------------------------------------------------------------------- #
    def _try_acquire_random(
        self, redis_key: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Attempt to lock a provider chosen at random.

        Returns the provider dict with helper fields added, or ``None`` when no
        provider could be locked.
        """
        shuffled = providers[:]
        random.shuffle(shuffled)

        return self._try_acquire_deterministic(
            redis_key=redis_key, providers=shuffled
        )

    def _try_acquire_deterministic(
        self, redis_key: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Iterate over *providers* in order and acquire the first free one.
        """
        for provider in providers:
            field = self._provider_field(provider)
            if self.lock_manager.acquire_provider(redis_key, field):
                if self._acquire_host_if_needed(provider):
                    provider["__chosen_field"] = field
                    return provider
                # Host lock failed – release provider lock and continue
                self.lock_manager.release_provider(redis_key, field)

        return None

    def _acquire_host_if_needed(self, provider: Dict) -> bool:
        """
        Acquire a host‑wide lock if the provider payload specifies a host.

        Returns ``True`` when either no host is defined or the host lock was
        successfully obtained.
        """
        host_name = provider.get("host") or provider.get("server")
        if not host_name:
            return True

        host_key = self._host_key(host_name)
        if self.lock_manager.acquire_host(host_key):
            provider["__host_key"] = host_key
            return True
        return False

    # --------------------------------------------------------------
    # Helper methods for persisting the last‑used host
    # --------------------------------------------------------------
    @staticmethod
    def _last_host_key(redis_key: str) -> str:
        """Redis key used to store the last host that served a model."""
        return f"{redis_key}:last_host"

    def _get_last_host(self, redis_key: str) -> Optional[str]:
        """Retrieve the previously stored host name for *redis_key*."""
        return self.redis_client.get(self._last_host_key(redis_key))

    def _set_last_host(self, redis_key: str, host_name: str) -> None:
        """Persist *host_name* as the last host for *redis_key*."""
        self.redis_client.set(self._last_host_key(redis_key), host_name)

    # ------------------------------------------------------------------- #
    # Redis key helpers
    # ------------------------------------------------------------------- #
    @staticmethod
    def _host_key(host_name: str) -> str:
        """Redis key used for host‑level locking."""
        return f"host:{host_name}"

    @staticmethod
    def _replace_provider_key_chars(name: str) -> str:
        """Replace characters that are not safe for Redis keys."""
        # ``ChooseProviderStrategyI`` defines ``REPLACE_PROVIDER_KEY`` – we
        # replicate its behaviour here to avoid a direct dependency.
        for ch in [" ", "/", "\\", "."]:
            name = name.replace(ch, "_")
        return name

    def _redis_key(self, model_name: str) -> str:
        """
        Construct the Redis hash key that stores provider lock fields for a
        particular model.
        """
        safe_name = self._replace_provider_key_chars(model_name)
        return f"model:{safe_name}"

    def _provider_field(self, provider: Dict) -> str:
        """
        Build the field name used inside the model hash to represent the lock
        status of *provider*.
        """
        provider_id = self._provider_key(provider)
        return f"{provider_id}:is_chosen"

    # ------------------------------------------------------------------- #
    # Buffer / initialisation utilities
    # ------------------------------------------------------------------- #
    def _clear_buffers(self) -> None:
        """
        Reset Redis state for all models known to the API configuration.

        The method deletes any existing initialisation flags and provider lock
        fields, then re‑creates the hash with all providers marked as free.
        """
        active_models = self._api_model_config.active_models
        models_cfg = self._api_model_config.models_configs

        for _, model_names in active_models.items():
            for model_name in model_names:
                redis_key = self._redis_key(model_name)
                providers = models_cfg[model_name]["providers"]

                # Remove old initialisation flag (if any)
                init_flag = f"{redis_key}:initialized"
                self.redis_client.delete(init_flag)

                # Reset all provider fields to "false"
                for p in providers:
                    field = self._provider_field(p)
                    self.redis_client.hset(redis_key, field, "false")

                # Re‑set the flag so that future calls treat the model as
                # initialised.
                self.redis_client.set(init_flag, "1")

    # ------------------------------------------------------------------- #
    # Compatibility shim – required by the original abstract base class
    # ------------------------------------------------------------------- #
    def _provider_key(self, provider: Dict) -> str:
        """
        Return a deterministic identifier for a provider.

        The original implementation expected a ``_provider_key`` method in the
        abstract base class; we keep the same contract here.
        """
        # Prefer an explicit ``id`` field, otherwise fall back to ``name``.
        return str(
            provider.get("id")
            or provider.get("name")
            or provider.get("host")
            or "unknown"
        )

    def _print_provider_status(self, redis_key: str, providers: List[Dict]) -> None:
        """
        Print the lock status of each provider stored in the Redis hash
        ``redis_key``.  Uses emojis for a quick visual cue:

        *  – provider is free (`'false'` or missing)
        *  – provider is currently taken (`'true'`)

        The output is formatted in a table‑like layout for readability.
        """
        try:
            # Retrieve the entire hash; missing fields default to None
            hash_data = self.redis_client.hgetall(redis_key)
        except Exception as exc:
            print(f"[⚠️] Could not read Redis key '{redis_key}': {exc}")
            return

        print("\nProvider lock status:")
        print("-" * 40)
        for provider in providers:
            field = self._provider_field(provider)
            status = hash_data.get(field, "false")
            icon = "" if status == "true" else ""
            # Show a short identifier for the provider (fallback to field)
            provider_id = provider.get("id") or provider.get("name") or field
            print(f"{icon}  {provider_id:<30} [{field}]")
        print("-" * 40)
