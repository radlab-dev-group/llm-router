"""
First Available Optimization Strategy module.

Provides an optimized load‑balancing strategy that reuses previously selected
hosts when possible, reducing latency and improving cache utilization.
"""

import logging
from typing import List, Dict, Optional, Any, Callable

from llm_router_api.core.monitor.keep_alive import KeepAlive
from llm_router_api.core.utils import StrategyHelpers
from llm_router_api.base.constants import (
    REDIS_HOST,
    REDIS_PORT,
    KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS,
    PROVIDER_MONITOR_INTERVAL_SECONDS,
)
from llm_router_api.core.monitor.keep_alive_monitor import KeepAliveMonitor
from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy


class FirstAvailableOptimStrategy(FirstAvailableStrategy):
    """
    Optimized version of :class:`FirstAvailableStrategy` that tries to reuse
    the previously used host for a model before falling back to the generic
    first‑available logic.

    This strategy tracks host usage in Redis and prefers hosts that already
    have the requested model loaded, aiming to minimise model loading time.
    """

    def __init__(
        self,
        models_config_path: str,
        redis_host: str = REDIS_HOST,
        redis_port: int = REDIS_PORT,
        redis_db: int = 0,
        timeout: int = 60,
        monitor_check_interval: float = PROVIDER_MONITOR_INTERVAL_SECONDS,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
        ka_monitor_check_interval: float = KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS,
    ) -> None:
        """
        Initialise the optimized first‑available strategy.

        Parameters
        ----------
        models_config_path: str
            Path to the models configuration file.
        redis_host: str, optional
            Hostname of the Redis server (default from :data:`REDIS_HOST`).
        redis_port: int, optional
            Port of the Redis server (default from :data:`REDIS_PORT`).
        redis_db: int, optional
            Redis database index to use.
        timeout: int, optional
            Request timeout in seconds.
        monitor_check_interval: float, optional
            Interval (seconds) between keep‑alive monitor checks.
        clear_buffers: bool, optional
            If ``True``, clear optimisation‑related Redis keys on start.
        logger: logging.Logger, optional
            Logger instance to use; a default logger is created if omitted.
        ka_monitor_check_interval: float, optional
            Interval (seconds) for the internal keep‑alive monitor thread.
        """
        super().__init__(
            models_config_path=models_config_path,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            timeout=timeout,
            monitor_check_interval=monitor_check_interval,
            clear_buffers=clear_buffers,
            logger=logger,
            strategy_prefix="fa_optim_",
        )
        if clear_buffers:
            self._clear_buffer()

        # Initialize and start the idle monitor
        self._keep_alive = KeepAlive(
            models_configs=self._api_model_config.models_configs,
            logger=self.logger,
        )

        # Monitor = schedule + Redis + condition "whether host is free"
        self.keep_alive_monitor = KeepAliveMonitor(
            redis_client=self.redis_client,
            check_interval=ka_monitor_check_interval,
            logger=self.logger,
            keep_alive=self._keep_alive,
            is_host_free_callback=self._is_host_free,
            clear_buffers=clear_buffers,
            redis_prefix="keepalive",
        )
        self.keep_alive_monitor.start()

    # -----------------------------------------------------------------
    # Overridden public API
    # -----------------------------------------------------------------
    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict | None:
        """
        Choose a provider for *model_name* using the optimization steps.

        The method attempts three optimization steps before falling back to the
        base implementation:

        1. Reuse the last host that served the model.
        2. Reuse any host that already has the model loaded.
        3. Pick a host that does not yet have the model.

        Parameters
        ----------
        model_name: str
            Name of the model to obtain a provider for.
        providers: List[Dict]
            List of candidate provider dictionaries.
        options: dict, optional
            Additional options that may influence provider selection.

        Returns
        -------
        dict | None
            The selected provider dictionary, or ``None`` if no provider
            could be chosen.
        """
        if not providers:
            return None

        redis_key, _ = self.init_provider(
            model_name=model_name, providers=providers, options=options
        )
        if not redis_key:
            return None

        # Helper to verify that a provider is still considered active.
        def _is_active(p: Dict) -> bool:
            active = self._get_active_providers(
                model_name=model_name, providers=providers
            )
            return any(p["id"] == act["id"] for act in active)

        # ---- Step 1 -------------------------------------------------
        provider = self._step1_last_host(model_name, providers)
        if provider:
            if _is_active(provider):
                self._record_selection(model_name, provider)
                return provider
            self.put_provider(model_name, provider)

        # ---- Step 2 -------------------------------------------------
        provider = self._step2_existing_hosts(model_name, providers)
        if provider:
            if _is_active(provider):
                self._record_selection(model_name, provider)
                return provider
            self.put_provider(model_name, provider)

        # ---- Step 3 -------------------------------------------------
        provider = self._step3_unused_host(model_name, providers)
        if provider:
            if _is_active(provider):
                self._record_selection(model_name, provider)
                return provider
            self.put_provider(model_name, provider)

        # ---- Fallback -----------------------------------------------
        provider = super().get_provider(
            model_name=model_name, providers=providers, options=options
        )
        if provider:
            self._record_selection(model_name, provider)

        return provider

    def stop_idle_monitor(self) -> None:
        """
        Stop the idle monitor thread that checks host availability.
        """
        self.keep_alive_monitor.stop()

    # -----------------------------------------------------------------
    # Helper utilities
    # -----------------------------------------------------------------
    def _last_host_key(self, model_name: str) -> str:
        """Redis key that stores the last host used for a given model."""
        return f"{self._get_redis_key(model_name)}:last_host"

    def _last_used_key(self, model_name: str) -> str:
        """Redis key that stores the timestamp of the last model usage."""
        return f"{self._get_redis_key(model_name)}:last_used"

    def _model_hosts_set_key(self, model_name: str) -> str:
        """Redis set key that holds all hosts where *model_name* is loaded."""
        return f"{self._get_redis_key(model_name)}:hosts"

    def _host_occupancy_key(self, host_name: str) -> str:
        """Redis hash key that stores the model currently occupying *host_name*."""
        return self._host_key(host_name)

    def _try_acquire(self, model_name: str, provider: Dict) -> Optional[Dict]:
        """
        Attempt to acquire the provider for *model_name* using the Lua script.

        On success, the provider dict is enriched with ``__chosen_field`` and
        returned; otherwise ``None`` is returned.

        Parameters
        ----------
        model_name: str
            The model for which the provider is being acquired.
        provider: dict
            Provider description dictionary.

        Returns
        -------
        dict | None
            The enriched provider dictionary if acquisition succeeded,
            otherwise ``None``.
        """
        field = self._provider_field(provider)
        try:
            ok = int(
                self._acquire_script(
                    keys=[self._get_redis_key(model_name)], args=[field]
                )
            )
            if ok == 1:
                provider["__chosen_field"] = field
                return provider
        except Exception:
            pass
        return None

    def _select_provider(
        self,
        model_name: str,
        providers: List[Dict],
        host_predicate: Callable[[str], bool],
    ) -> Optional[Dict]:
        """
        Iterate over *providers*, keep only those whose host satisfies
        ``host_predicate`` **and** is free for *model_name*. Return the first
        provider that can be successfully acquired.

        Parameters
        ----------
        model_name: str
            Model name for which a provider is required.
        providers: List[Dict]
            Candidate providers.
        host_predicate: Callable[[str], bool]
            Function that returns ``True`` for acceptable hosts.

        Returns
        -------
        dict | None
            The first successfully acquired provider, or ``None`` if none
            could be acquired.
        """
        for provider in providers:
            host = StrategyHelpers.host_from_provider(provider)
            if not host:
                continue
            if not host_predicate(host):
                continue
            if not self._is_host_free(host, model_name):
                continue
            acquired = self._try_acquire(model_name, provider)
            if acquired:
                return acquired
        return None

    # -----------------------------------------------------------------
    # Occupancy check – now decodes the stored model name
    # -----------------------------------------------------------------
    def _is_host_free(self, host: str, model_name: str) -> bool:
        """
        Check if a host is free for a given model.

        The method reads the current model occupying the host from Redis,
        normalizes both the stored and requested model names, and compares them.

        Parameters
        ----------
        host: str
            Host identifier.
        model_name: str
            Requested model name.

        Returns
        -------
        bool
            ``True`` if the host is either free or already occupied by the same
            model, ``False`` otherwise.
        """
        occ_key = self._host_occupancy_key(host)
        current_model_raw = StrategyHelpers.decode_redis(
            self.redis_client.hget(occ_key, "model")
        )

        current_model = StrategyHelpers.normalize_model_name(current_model_raw)
        requested_model = StrategyHelpers.normalize_model_name(model_name)

        self.logger.debug(
            "[keep-alive] _is_host_free current_model=%r requested_model=%r host=%s",
            current_model,
            requested_model,
            host,
        )

        return (not current_model) or (current_model == requested_model)

    # -----------------------------------------------------------------
    # Step 1 – reuse last host (decode occupancy value)
    # -----------------------------------------------------------------
    def _step1_last_host(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Try to acquire a provider on the host that was used the last time this
        model was selected.

        Parameters
        ----------
        model_name: str
            Model name.
        providers: List[Dict]
            Candidate providers.

        Returns
        -------
        dict | None
            Provider from the last host if it is free, otherwise ``None``.
        """
        last_host = StrategyHelpers.decode_redis(
            self.redis_client.get(self._last_host_key(model_name))
        )
        if not last_host:
            return None

        # Verify host is free for this model.
        if not self._is_host_free(last_host, model_name):
            return None

        return self._select_provider(
            model_name,
            providers,
            host_predicate=lambda h: h == last_host,
        )

    # -----------------------------------------------------------------
    # Step 2 – reuse any host that already runs this model
    # -----------------------------------------------------------------
    def _step2_existing_hosts(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Look for hosts that already have *model_name* loaded and try to acquire
        a free provider.

        Parameters
        ----------
        model_name: str
            Model name.
        providers: List[Dict]
            Candidate providers.

        Returns
        -------
        dict | None
            Provider from a known host if one is free, otherwise ``None``.
        """
        hosts_key = self._model_hosts_set_key(model_name)
        host_bytes = self.redis_client.smembers(hosts_key)
        if not host_bytes:
            return None
        known_hosts = {StrategyHelpers.decode_redis(b) for b in host_bytes}

        return self._select_provider(
            model_name,
            providers,
            host_predicate=lambda h: h in known_hosts,
        )

    # -----------------------------------------------------------------
    # Step 3 – pick a host that does NOT already have this model loaded
    # -----------------------------------------------------------------
    def _step3_unused_host(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Find a host that does **not** already run ``model_name`` and acquire a
        provider on it.

        Parameters
        ----------
        model_name: str
            Model name.
        providers: List[Dict]
            Candidate providers.

        Returns
        -------
        dict | None
            Provider from an unused host if one is free, otherwise ``None``.
        """
        known_hosts_key = self._model_hosts_set_key(model_name)
        known_hosts_bytes = self.redis_client.smembers(known_hosts_key)
        known_hosts = (
            {StrategyHelpers.decode_redis(b) for b in known_hosts_bytes}
            if known_hosts_bytes
            else set()
        )

        return self._select_provider(
            model_name,
            providers,
            host_predicate=lambda h: h not in known_hosts,
        )

    # -----------------------------------------------------------------
    # Step 5 – bookkeeping after a successful acquisition
    # -----------------------------------------------------------------
    def _record_selection(self, model_name: str, provider: Dict) -> None:
        """
        Store the chosen host as the *last host* and update bookkeeping
        structures.

        Parameters
        ----------
        model_name: str
            Model name that was selected.
        provider: dict
            Provider dictionary that was selected.
        """
        host = StrategyHelpers.host_from_provider(provider)
        if not host:
            return

        # 1. Remember the last host.
        self.redis_client.set(self._last_host_key(model_name), host)

        # 2. Add host to the model‑specific set.
        self.redis_client.sadd(self._model_hosts_set_key(model_name), host)

        # 3. Mark the host as occupied by this model.
        occ_key = self._host_occupancy_key(host)
        self.redis_client.hset(
            occ_key, "model", StrategyHelpers.normalize_model_name(model_name)
        )

        # 4. KeepAlive state is now owned by KeepAliveMonitor.
        keep_alive_value = provider.get("keep_alive")
        self.keep_alive_monitor.record_usage(
            model_name=model_name,
            host=host,
            keep_alive=keep_alive_value,
        )

    # -----------------------------------------------------------------
    # Buffer cleanup
    # -----------------------------------------------------------------
    def _clear_buffer(self) -> None:
        """
        Remove all Redis keys used by this optimization strategy.
        """
        suffixes = (":last_host", ":hosts", ":occupancy")
        for suffix in suffixes:
            for key in self.redis_client.scan_iter(match=f"*{suffix}"):
                self.logger.debug(f"Removing {self} => {key} from redis")
                self.redis_client.delete(key)
