from __future__ import annotations

import abc
import random
import logging

from typing import Dict, List, Optional, Any, Tuple

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

from llm_router_api.base.lb.strategy import ChooseProviderStrategyI
from llm_router_api.base.lb.redis_lock_manager import RedisLockManager
from llm_router_api.base.lb.provider_monitor import ProviderMonitorWrapper


class RedisBasedStrategyI(ChooseProviderStrategyI, abc.ABC):
    """
    Strategy that selects the first free provider for a model using Redis‑based
    coordination.

    The class implements the abstract: class:`ChooseProviderStrategyI` interface
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
        redis_keys_prefix: Optional[str] = "fa_optim_",
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
        redis_keys_prefix: Optional, default `fa_gpu_mem_` (string)
            This prefix will be used to prepare each key stored in redis
        """
        if not _REDIS_AVAILABLE:  # pragma: no cover
            raise RuntimeError(
                "Redis is not installed. Install the `redis` package to use "
                "RedisBasedStrategy."
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
        self.redis_keys_prefix = (
            redis_keys_prefix if redis_keys_prefix else "fa_optim_"
        )

        if clear_buffers:
            self._clear_buffers()

    def init_get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], bool]:
        if not providers:
            return None, False

        # Register providers for monitoring (only once per model)
        self.monitor.add_providers(model_name, providers)

        redis_key = self._redis_key(model_name)

        # Ensure fields exist; if someone removed the hash, recreate it
        if not self.redis_client.exists(redis_key):
            for p in providers:
                self.redis_client.hset(redis_key, self._provider_field(p), "false")

        is_random = bool(options and options.get("random_choice", False))
        return redis_key, is_random

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
        host_name = self._provider_key(provider)
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
    def _last_host_key(self, redis_key: str) -> str:
        """Redis key used to store the last host that served a model."""
        return f"{self.redis_keys_prefix}{redis_key}:last_host"

    def _get_last_host(self, redis_key: str) -> Optional[str]:
        """Retrieve the previously stored host name for *redis_key*."""
        return self.redis_client.get(self._last_host_key(redis_key))

    def _set_last_host(self, redis_key: str, host_name: str) -> None:
        """Persist *host_name* as the last host for *redis_key*."""
        self.redis_client.set(self._last_host_key(redis_key), host_name)

    # ------------------------------------------------------------------- #
    # Redis key helpers
    # ------------------------------------------------------------------- #
    def _host_key(self, host_name: str) -> str:
        """Redis key used for host‑level locking."""
        return f"{self.redis_keys_prefix}host:{host_name}"

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
        return f"{self.redis_keys_prefix}model:{safe_name}"

    def _provider_field(self, provider: Dict) -> str:
        """
        Build the field name used inside the model hash to represent the lock
        status of *provider*.
        """
        provider_id = self._provider_key(provider)
        return f"{self.redis_keys_prefix}{provider_id}:is_chosen"

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

                # Remove the old initialization flag (if any)
                init_flag = f"{redis_key}:initialized"
                self.redis_client.delete(init_flag)

                # Reset all provider fields to "false"
                for p in providers:
                    field = self._provider_field(p)
                    self.redis_client.hset(redis_key, field, "false")

                # Re‑set the flag so that future calls
                # treat the model as initialized.
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
            or provider.get("api_host")
            or provider.get("name")
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
            icon = "🔴" if status == "true" else "🟢"
            # Show a short identifier for the provider (fallback to field)
            provider_id = self._provider_key(provider)
            print(f"{icon}  {provider_id:<30} [{field}]")
        print("-" * 40)
