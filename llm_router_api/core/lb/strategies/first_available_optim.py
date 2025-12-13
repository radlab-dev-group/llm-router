import logging

from typing import List, Dict, Optional, Any, Callable

from llm_router_api.base.constants import REDIS_HOST, REDIS_PORT
from llm_router_api.core.keep_alive import KeepAlive
from llm_router_api.core.monitor.keep_alive_monitor import KeepAliveMonitor
from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy
from llm_router_api.core.utils import StrategyHelpers


class FirstAvailableOptimStrategy(FirstAvailableStrategy):
    """
    Optimized version of :class:`FirstAvailableStrategy` that tries to reuse
    the previously used host for a model before falling back to the generic
    first‑available logic.
    """

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
        keep_alive_monitor_check_interval: float = 1.0,
    ) -> None:
        super().__init__(
            models_config_path=models_config_path,
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            timeout=timeout,
            check_interval=check_interval,
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

        # 2) Monitor = harmonogram + Redis + warunek "czy host wolny"
        self.keep_alive_monitor = KeepAliveMonitor(
            redis_client=self.redis_client,
            check_interval=keep_alive_monitor_check_interval,
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
        """Execute the optimisation steps before falling back to the base implementation."""
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
        """Stop the idle monitor thread."""
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
        ``host_predicate`` **and** is free for *model_name*.  Return the first
        provider that can be successfully acquired.
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
        """Check if a host is free for a given model."""
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
        """Try to acquire a provider on the host that was used the last time this model was selected."""
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
        """Look for hosts that already have *model_name* loaded and try to acquire a free provider."""
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
        """Find a host that does **not** already run ``model_name`` and acquire a provider on it."""
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
        """Store the chosen host as the *last host* and update bookkeeping structures."""
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
        """Remove all Redis keys used by this optimisation strategy."""
        suffixes = (":last_host", ":hosts", ":occupancy")
        for suffix in suffixes:
            for key in self.redis_client.scan_iter(match=f"*{suffix}"):
                self.logger.debug(f"Removing {self} => {key} from redis")
                self.redis_client.delete(key)
