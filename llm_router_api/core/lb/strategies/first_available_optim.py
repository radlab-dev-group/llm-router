"""
Optimized first‑available load‑balancing strategy.

This module defines :class:`FirstAvailableOptimStrategy`, an extension of
:class:`~llm_router_api.core.lb.strategies.first_available.FirstAvailableStrategy`
that attempts to reuse a previously used host before falling back to the generic
first‑available logic.  It also integrates an :class:`~llm_router_api.core.monitor.idle_monitor.IdleMonitor`
to keep idle models alive by periodically sending a short keep‑alive prompt.
"""

import time
import logging
from typing import Any, Dict, List, Optional

from llm_router_api.base.constants import REDIS_HOST, REDIS_PORT
from llm_router_api.core.monitor.idle_monitor import IdleMonitor
from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy


class FirstAvailableOptimStrategy(FirstAvailableStrategy):
    """
    Optimized version of :class:`FirstAvailableStrategy`.

    The optimisation consists of three steps:

    1. Re‑use the host that was last used for the model.
    2. Re‑use any host that already runs the model.
    3. Choose a host that **does not** already run the model.

    If none of the steps succeed, the base implementation is used as a fallback.
    The class also starts an :class:`IdleMonitor` instance that periodically
    sends a keep‑alive prompt to idle models.
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
        idle_time_seconds: int = 3600,
    ) -> None:
        """
        Initialise the strategy and start idle monitoring.

        Args:
            models_config_path: Path to the JSON/YAML file containing model
                configuration.
            redis_host: Hostname of the Redis server.
            redis_port: Port of the Redis server.
            redis_db: Redis database index.
            timeout: Maximum time (seconds) to wait for a provider.
            check_interval: Interval (seconds) for the idle monitor loop.
            clear_buffers: If ``True``, remove any leftover Redis keys from a
                previous run.
            logger: Optional logger; a module‑level logger is used if omitted.
            idle_time_seconds: Time (seconds) after which a model is considered
                idle and a keep‑alive prompt will be sent.
        """
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
        self.idle_time_seconds = idle_time_seconds
        if clear_buffers:
            self._clear_buffer()

        # Initialise and start the idle monitor.
        self._idle_monitor = IdleMonitor(
            redis_client=self.redis_client,
            idle_time_seconds=self.idle_time_seconds,
            check_interval=self.check_interval,
            logger=self.logger,
            send_prompt_callback=self._send_prompt,
            get_last_host_key=self._last_host_key,
            get_last_used_key=self._last_used_timestamp_key,
            is_host_free_callback=self._is_host_free,
        )
        self._idle_monitor.start()

    # ----------------------------------------------------------------------
    # Public API – provider selection (augmented with timestamp handling)
    # ----------------------------------------------------------------------
    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict]:
        """
        Select a provider for *model_name* using the optimisation steps.

        The method records the selected provider in Redis and updates
        bookkeeping structures used by the idle monitor.
        """
        # Step 1 – try to reuse the last host that served this model.
        last_host_key = self._last_host_key(model_name)
        last_host = self.redis_client.get(last_host_key)
        if last_host:
            host = last_host.decode()
            provider = self._provider_on_host(host, providers, model_name)
            if provider:
                self._record_selection(model_name, provider)
                self._store_last_used_timestamp(model_name)
                return provider

        # Step 2 – reuse any host that already runs the model.
        provider = self._step2_existing_host(model_name, providers)
        if provider:
            self._record_selection(model_name, provider)
            self._store_last_used_timestamp(model_name)
            return provider

        # Step 3 – pick a host that does NOT already have this model loaded.
        provider = self._step3_unused_host(model_name, providers)
        if provider:
            self._record_selection(model_name, provider)
            self._store_last_used_timestamp(model_name)
            return provider

        # Fallback to the base implementation.
        provider = super().get_provider(model_name, providers, options)
        if provider:
            self._record_selection(model_name, provider)
            self._store_last_used_timestamp(model_name)
        return provider

    # ----------------------------------------------------------------------
    # Helper for Step 1 – find a provider on a specific host
    # ----------------------------------------------------------------------
    def _provider_on_host(
        self, host: str, providers: List[Dict], model_name: str
    ) -> Optional[Dict]:
        """
        Return a provider that runs on *host* and can be acquired.
        """
        for provider in providers:
            if self._host_from_provider(provider) != host:
                continue
            if not self._is_host_free(host, model_name):
                continue
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
                continue
        return None

    # ----------------------------------------------------------------------
    # Step 2 – reuse any host that already runs the model
    # ----------------------------------------------------------------------
    def _step2_existing_host(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Find a free provider on a host that already hosts *model_name*.
        """
        hosts_key = self._model_hosts_set_key(model_name)
        host_bytes = self.redis_client.smembers(hosts_key)
        if not host_bytes:
            return None
        known_hosts = {b.decode() for b in host_bytes}
        for provider in providers:
            host = self._host_from_provider(provider)
            if host not in known_hosts:
                continue
            if not self._is_host_free(host, model_name):
                continue
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
                continue
        return None

    # ----------------------------------------------------------------------
    # Step 3 – pick a host that does NOT already have this model loaded
    # ----------------------------------------------------------------------
    def _step3_unused_host(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Find a free provider on a host that does not yet run *model_name*.
        """
        known_hosts_key = self._model_hosts_set_key(model_name)
        known_hosts_bytes = self.redis_client.smembers(known_hosts_key)
        known_hosts = (
            {b.decode() for b in known_hosts_bytes} if known_hosts_bytes else set()
        )
        for provider in providers:
            host = self._host_from_provider(provider)
            if not host or host in known_hosts:
                continue
            if not self._is_host_free(host, model_name):
                continue
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
                continue
        return None

    # ----------------------------------------------------------------------
    # Bookkeeping – after a successful provider allocation
    # ----------------------------------------------------------------------
    def _record_selection(self, model_name: str, provider: Dict) -> None:
        """
        Persist the chosen host and update occupancy structures.
        """
        host = self._host_from_provider(provider)
        if not host:
            return

        # 1. Remember the last host for the model.
        self.redis_client.set(self._last_host_key(model_name), host)

        # 2. Add host to the set of hosts known to run the model.
        self.redis_client.sadd(self._model_hosts_set_key(model_name), host)

        # 3. Mark the host as occupied by this model.
        occ_key = self._host_occupancy_key(host)
        self.redis_client.hset(occ_key, "model", model_name)

    # ----------------------------------------------------------------------
    # Timestamp handling – used by :class:`IdleMonitor`
    # ----------------------------------------------------------------------
    def _store_last_used_timestamp(self, model_name: str) -> None:
        """
        Save the current epoch seconds as the model's last‑used timestamp.
        """
        ts_key = self._last_used_timestamp_key(model_name)
        self.redis_client.set(ts_key, int(time.time()))

    def _last_used_timestamp_key(self, model_name: str) -> str:
        """Redis key that holds the last‑used timestamp for *model_name*."""
        return f"{self._get_redis_key(model_name)}:last_used"

    # ----------------------------------------------------------------------
    # Helper used by :class:`IdleMonitor` – can be swapped out in tests
    # ----------------------------------------------------------------------
    def _send_prompt(self, model_name: str, prompt: str) -> None:
        """
        Send a keep‑alive prompt to *model_name* (stub implementation).
        """
        self.logger.info(
            f"Sending keep‑alive prompt to model '{model_name}': {prompt}"
        )
        # TODO:
        # client = get_llm_client_for_model(model_name)
        # client.complete(prompt)

    # ----------------------------------------------------------------------
    # Buffer clearing – removes all auxiliary Redis keys used by this strategy
    # ----------------------------------------------------------------------
    def _clear_buffer(self) -> None:
        """
        Delete Redis keys with suffixes used by the optimisation strategy.
        """
        suffixes = (":last_host", ":hosts", ":occupancy", ":last_used")
        for suffix in suffixes:
            for key in self.redis_client.scan_iter(match=f"*{suffix}"):
                self.logger.debug(f"Removing key {key} from Redis")
                self.redis_client.delete(key)

    # ----------------------------------------------------------------------
    # Miscellaneous helpers (unchanged)
    # ----------------------------------------------------------------------
    @staticmethod
    def _host_from_provider(provider: Dict) -> Optional[str]:
        """
        Extract the host identifier from a provider configuration.
        """
        return provider.get("api_host") or provider.get("host")

    def _last_host_key(self, model_name: str) -> str:
        """
        Redis key that stores the last host used for *model_name*.
        """
        return f"{self._get_redis_key(model_name)}:last_host"

    def _model_hosts_set_key(self, model_name: str) -> str:
        """
        Redis set key that holds all hosts where *model_name* is loaded.
        """
        return f"{self._get_redis_key(model_name)}:hosts"

    def _host_occupancy_key(self, host_name: str) -> str:
        """
        Redis hash key that records which model occupies *host_name*."""
        return self._host_key(host_name)

    def _is_host_free(self, host: str, model_name: str) -> bool:
        """
        Return ``True`` if *host* is unoccupied or occupied by the same model.
        """
        occ_key = self._host_occupancy_key(host)
        current_model = self.redis_client.hget(occ_key, "model")
        return not (current_model and current_model != model_name)
