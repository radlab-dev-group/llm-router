"""
Redis based strategy interface.

This module defines an abstract base class that combines load‑balancing
strategy selection with Redis‑backed health‑checking.  It is used by the
router to coordinate provider allocation across multiple processes or
hosts, guaranteeing that a particular provider is assigned to at most one
consumer at any time.

The implementation relies on Lua scripts for atomic acquire/release
operations and uses a per‑model Redis hash to store lock flags.
"""

import random
import logging

from abc import ABC
from typing import Any, Dict, List, Optional, Tuple

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from llm_router_api.base.constants import (
    REDIS_PORT,
    REDIS_HOST,
    REDIS_DB,
    REDIS_PASSWORD,
    REDIS_PROTOCOL,
    PROVIDER_MONITOR_INTERVAL_SECONDS,
    PROVIDER_MONITOR_PING_TIMEOUT_SECONDS,
    PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES,
)
from llm_router_api.core.monitor.provider_monitor import RedisProviderMonitor
from llm_router_api.core.lb.strategy_interface import ChooseProviderStrategyI

logger = logging.getLogger(__name__)


class RedisBasedStrategy(ChooseProviderStrategyI, ABC):
    """
    Strategy that selects the first free provider for a model using Redis.

    This class merges two responsibilities:

    * **Load‑balancing** – Implements the
      :class:`~llm_router_api.core.lb.strategy.ChooseProviderStrategyI`
      contract, choosing a provider for a given model.
    * **Health‑checking** – Inherits from
      :class:`~llm_router_api.core.monitor.redis_health_interface.RedisBasedHealthCheckInterface`
      to monitor provider health via Redis.

    By storing a per‑model hash in Redis where each field represents a
    provider’s lock flag, the strategy guarantees that only one worker can
    acquire a provider at a time, even when the workers run on different
    machines.  The acquisition and release are performed atomically using
    Lua scripts, eliminating race conditions.

    The constructor accepts optional Redis connection parameters so the
    strategy can be pointed at any Redis instance, and a ``strategy_prefix``
    can be used to namespace keys when multiple strategies share the same
    Redis server.
    """

    def __init__(
        self,
        models_config_path: str,
        redis_host: str = REDIS_HOST,
        redis_password: str = REDIS_PASSWORD,
        redis_port: int = REDIS_PORT,
        redis_db: int = REDIS_DB,
        redis_protocol: int = REDIS_PROTOCOL,
        monitor_check_interval: float = PROVIDER_MONITOR_INTERVAL_SECONDS,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
        strategy_prefix: Optional[str] = "",
    ) -> None:
        """
        Initialize the FirstAvailableStrategy.

        Parameters
        ----------
        models_config_path : str
            Path to the models configuration file.
        redis_host : str, optional
            Redis server host. Default is ``"192.168.100.67"``.
        redis_port : int, optional
            Redis server port. Default is ``6379``.
        redis_db : int, optional
            Redis database number. Default is ``0``.
        redis_protocol : int, optional
            Redis protocol version (RESP2 vs RESP3). Default is ``3``.
        monitor_check_interval : float, optional
            Time to sleep [in monitor module] between checks
            for available providers (in seconds).
            Default is ``15``.
        clear_buffers:
            Whether to clear all buffers when starting. Default is ``True``.
        """
        ChooseProviderStrategyI.__init__(
            self=self, models_config_path=models_config_path, logger=logger
        )

        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
            password=redis_password,
            protocol=redis_protocol,
        )

        self.redis_health_check = RedisProviderMonitor(
            redis_client=self.redis_client,
            clear_buffers=clear_buffers,
            logger=logger,
            check_interval=monitor_check_interval,
            check_timeout=PROVIDER_MONITOR_PING_TIMEOUT_SECONDS,
            max_consecutive_failures=PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES,
        )

        self.strategy_prefix = strategy_prefix

        # Atomic acquire script – treat missing field as “available”
        self._acquire_script = self.redis_client.register_script(
            """
                local redis_key = KEYS[1]
                local field = ARGV[1]
                local v = redis.call('HGET', redis_key, field)
                -- v == false  -> field does not exist (nil)
                -- v == 'false' -> explicitly marked as free
                if v == false or v == 'false' then
                    redis.call('HSET', redis_key, field, 'true')
                    return 1
                end
                return 0
            """
        )

        # Atomic release script – simply delete the field (no race condition)
        self._release_script = self.redis_client.register_script(
            """
                local redis_key = KEYS[1]
                local field = ARGV[1]
                -- Delete the field; returns 1 if field existed, 0 otherwise
                redis.call('HDEL', redis_key, field)
                return 1
            """
        )

        if clear_buffers:
            self._clear_buffers()

    def init_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], bool]:
        """
        Prepare Redis structures for a model and optionally enable random choice.

        This method is invoked once per model during strategy start‑up.  It
        registers the providers with the monitoring subsystem, ensures that a
        Redis hash exists for the model, and populates the hash fields with a
        ``'false'`` value (meaning *free*) if the hash is missing.  The returned
        ``redis_key`` is the base key used for all subsequent lock operations.

        Parameters
        ----------
        model_name: str
            The logical name of the model (e.g., ``"gpt‑4"``).
        providers: List[Dict]
            A list of provider configuration dictionaries.
        options: Optional[dict], optional
            If ``options.get("random_choice")`` is true, the caller intends to
            acquire a provider at random; the flag is propagated to the caller.

        Returns
        -------
        Tuple[Optional[str], bool]
            ``(redis_key, is_random)`` where ``redis_key`` is the Redis hash key
            for the model (or ``None`` if ``providers`` is empty) and ``is_random``
            reflects the ``random_choice`` option.
        """
        if not providers:
            return None, False
        # Register providers for monitoring (only once per model)
        self.redis_health_check.add_providers(model_name, providers)

        redis_key = self._get_redis_key(model_name)

        # Ensure fields exist; if someone removed the hash, recreate it
        if not self.redis_client.exists(redis_key):
            for p in providers:
                self.redis_client.hset(redis_key, self._provider_field(p), "false")

        # self._print_provider_status(redis_key, providers)

        is_random = options and options.get("random_choice", False)
        return redis_key, is_random

    def _get_redis_key(self, model_name: str) -> str:
        """
        Return Redis key prefix for a given model.
        """
        for ch in self.REPLACE_PROVIDER_KEY:
            model_name = model_name.replace(ch, "_")
        return f"model:{model_name}"

    def _host_key(self, host_name: str) -> str:
        """
        Return a Redis key that uniquely identifies a host.

        Host names may contain characters that are unsuitable for Redis keys.
        This method sanitises the name by replacing any character listed in
        ``self.REPLACE_PROVIDER_KEY`` with an underscore and then prefixes it
        with ``"host:"``.

        Parameters
        ----------
        host_name: str
            The raw host identifier (e.g., a hostname or IP address).

        Returns
        -------
        str
            A safe Redis key such as ``"host:my_server_01"``.
        """
        for ch in self.REPLACE_PROVIDER_KEY:
            host_name = host_name.replace(ch, "_")

        return f"host:{host_name}"

    def _provider_field(self, provider: dict) -> str:
        """
        Build the Redis hash field name that stores the chosen flag
        for a given provider.

        Parameters
        ----------
        provider : Dict
            Provider configuration dictionary.

        Returns
        -------
        str
            Field name in the format ``{provider_id}:is_chosen``.
        """
        provider_id = self._provider_key(provider)
        return f"{provider_id}:is_chosen"

    def _init_flag(self, model_name: str) -> str:
        """
        Build the Redis key used as an initialization flag for a model.

        Parameters
        ----------
        model_name : str
            Name of the model.

        Returns
        -------
        str
            Flag key in the format ``model:{model_name}:initialized``.
        """
        return f"{self._get_redis_key(model_name)}:initialized"

    # ----------------------------------------------------------------------
    # Helper methods
    # ----------------------------------------------------------------------
    def _try_acquire(self, model_name: str, provider: Dict) -> Optional[Dict]:
        """
        Atomically try to acquire *provider* for *model_name*.

        This is the acquisition hook shared by every Redis‑based selection
        loop (``_acquire_provider_step``, :meth:`_try_acquire_random_provider`,
        …).  The default implementation uses the classic boolean lock: the
        ``_acquire_script`` Lua script marks the provider's
        ``:is_chosen`` field ``'true'`` in the ``model:<model_name>`` hash
        only when the field is currently free (``'false'`` or missing).

        On success the provider dictionary is enriched with the
        ``__chosen_field`` entry and returned; ``None`` is returned when the
        provider is already taken or the acquisition raises (acquisition
        errors are non‑fatal – the caller simply tries the next candidate).

        Subclasses may override this hook to implement different
        concurrency models (e.g. per‑provider worker slots) without touching
        the selection loops.

        Parameters
        ----------
        model_name: str
            The model for which the provider is being acquired.
        provider: dict
            Provider description dictionary.

        Returns
        -------
        Optional[dict]
            The enriched provider dictionary if acquisition succeeded,
            otherwise ``None``.
        """
        provider_field = self._provider_field(provider)
        try:
            ok = int(
                self._acquire_script(
                    keys=[self._get_redis_key(model_name)], args=[provider_field]
                )
            )
            if ok == 1:
                provider["__chosen_field"] = provider_field
                return provider
        except Exception:
            # intentional: acquisition errors are non-fatal; this provider is
            # simply skipped and the next candidate is tried by the caller.
            pass
        return None

    def _try_acquire_random_provider(
        self, model_name: str, redis_key: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Attempt to acquire a provider chosen at random.

        A shallow copy of ``providers`` is shuffled so that each provider has
        an equal probability of being tried first; the original list is left
        untouched.  Each shuffled provider is then passed through the
        :meth:`_try_acquire` hook.  The first successfully acquired provider
        is returned.

        Parameters
        ----------
        model_name : str
            The model for which a provider is being acquired.
        redis_key : str
            The Redis hash key associated with the model (e.g.,
            ``model:<name>``); kept for signature compatibility.
        providers : List[Dict]
            A list of provider configuration dictionaries.  Each dictionary
            must contain sufficient information for :meth:`_provider_field`
            to generate a unique field name within the Redis hash.

        Returns
        -------
        Optional[Dict]
            The selected provider dictionary with an additional
            ``"__chosen_field"`` entry indicating the Redis hash field that
            was locked.  Returns ``None`` when no provider could be acquired
            (e.g. all are currently in use) or the list is empty.

        Notes
        -----
        * The random selection is *non‑deterministic* on each call.
        * The method does **not** block; it returns immediately after trying
          all shuffled providers.
        """
        shuffled = providers[:]
        random.shuffle(shuffled)
        for provider in shuffled:
            acquired = self._try_acquire(model_name, provider)
            if acquired:
                return acquired
        return None

    def has_available_provider(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[bool]:
        """
        Ask the health monitor whether *model_name* can be served right now.

        The check is non‑blocking and lets the caller skip a model that is
        known to be unable to serve a request instead of waiting for the
        selection ``timeout`` to expire.

        Returns
        -------
        Optional[bool]
            ``True``  – at least one registered provider is healthy;
            ``False`` – the model has registered providers but none of them is
            currently healthy;
            ``None``  – nothing is known about the model yet (it has never
            been registered with the monitor, e.g. cold start, or Redis is
            unreachable), so the caller must use the normal blocking
            selection path.
        """
        try:
            registered = self.redis_health_check.get_providers(model_name=model_name)
            if not registered:
                return None
            return bool(
                self._get_active_providers(
                    model_name=model_name, providers=providers
                )
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # intentional: availability probing is best-effort only; a Redis
            # outage must never break provider selection.
            return None

    def _get_active_providers(
        self, model_name: str, providers: List[Dict]
    ) -> List[Dict]:  # pylint: disable=unused-argument
        """
        Retrieve the list of currently active providers for a model.

        The method delegates to the monitoring component, which tracks the
        health status of each provider.  Only providers whose health check
        reports *active* are returned.

        Parameters
        ----------
        model_name: str
            The logical name of the model.
        providers: List[Dict]
            The full provider configuration list (kept for signature compatibility;
            it is not used directly).

        Returns
        -------
        List[Dict]
            A list containing the configuration dictionaries of active providers.
        """
        active_providers = self.redis_health_check.get_providers(
            model_name=model_name, only_active=True
        )
        return active_providers

    def _initialize_providers(self, model_name: str, providers: List[Dict]) -> None:
        """
        Ensure that the provider lock fields for *model_name* exist in Redis.

        This method is idempotent – it will create the hash fields only if the
        model has not been initialized before.  An auxiliary flag key
        ``model:{model_name}:initialized`` is used to guard against repeated
        initialization, which could otherwise overwrite the current lock state
        of providers that are already in use.

        Parameters
        ----------
        model_name : str
            The name of the model whose providers are being prepared.
        providers : List[Dict]
            A list of provider configuration dictionaries.  Each dictionary must
            contain enough information for :meth:`_provider_field` to generate a
            unique field name.

        Notes
        -----
        * The provider fields are stored in a Redis hash whose key is
          ``model:{model_name}``.  Each field is set to the string ``'false'``
          to indicate that the provider is currently free.
        * The initialization flag is a simple Redis key with value ``'1'``.
          Its existence signals that the hash has already been populated.
        """
        redis_key = self._get_redis_key(model_name)

        # Check if already initialized using a flag
        init_flag = self._init_flag(model_name)
        if self.redis_client.exists(init_flag):
            return

        # Initialize all providers as available
        for provider in providers:
            provider_field = self._provider_field(provider)
            self.redis_client.hset(redis_key, provider_field, "false")

        # Set initialization flag
        self.redis_client.set(init_flag, "1")

    def _clear_buffers(self) -> None:
        """
        Reset the Redis state for all active models.

        This method removes any existing initialization flags and provider
        lock fields, then re‑initialises the providers as available.  It is
        typically invoked during strategy start‑up to ensure a clean slate.
        """
        active_models = self._api_model_config.active_models
        models_configs = self._api_model_config.models_configs
        for _, models_names in active_models.items():
            for model_name in models_names:
                redis_key = self._get_redis_key(model_name)
                providers = models_configs[model_name]["providers"]
                if len(providers) > 0:
                    model_path = providers[0].get("model_path", "").strip()
                    if model_path:
                        model_name = model_path

                init_flag = self._init_flag(model_name)
                self.redis_client.delete(init_flag)

                for provider in providers:
                    provider_field = self._provider_field(provider)
                    self.redis_client.hset(redis_key, provider_field, "false")

                self._initialize_providers(
                    model_name=model_name, providers=providers
                )

    def _print_provider_status(self, redis_key: str, providers: List[Dict]) -> None:
        """
        Print the lock status of each provider stored in the Redis hash
        ``redis_key``.  Uses emojis for a quick visual cue:

        * 🟢 – provider is free (`'false'` or missing)
        * 🔴 – provider is currently taken (`'true'`)

        The output is formatted in a table‑like layout for readability.
        """
        _log = self.logger if self.logger is not None else logger
        try:
            # Retrieve the entire hash; missing fields default to None
            hash_data = self.redis_client.hgetall(redis_key)
        except Exception as exc:
            # Intentional: this is a best-effort diagnostic; a read failure
            # must never break the selection path, so log and bail out.
            _log.warning("Could not read Redis key '%s': %s", redis_key, exc)
            return

        _log.info("Provider lock status:")
        for provider in providers:
            field = self._provider_field(provider)
            status = hash_data.get(field, "false")
            # Show a short identifier for the provider (fallback to field)
            provider_id = provider.get("id") or provider.get("api_host") or field
            state = "locked" if status == "true" else "free"
            _log.info("  %-30s [%s] (%s)", provider_id, field, state)
