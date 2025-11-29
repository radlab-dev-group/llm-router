"""
Enhanced provider‑selection strategy.

The :class:`FirstAvailableOptimStrategy` builds on the classic
:class:`~llm_router_api.core.lb.first_available.FirstAvailableStrategy`
by adding three optimisation steps:

1. **Last‑host affinity** – if a previous request for the same model was
   handled on a host that still runs the model and the corresponding provider
   is free, that provider is chosen again.
2. **Other hosts with the model** – if the last host is busy, the strategy
   scans the remaining providers that host the model and picks the first free
   one.
3. **Fallback** – if no provider is free on any host that already has the
   model, the normal *first‑available* algorithm is executed.

A small piece of state is kept in Redis under the key
``model:<model_name>:last_host`` so that the affinity survives across
different processes or machines.
"""

import logging
from typing import List, Dict, Optional, Any

from llm_router_api.base.constants import REDIS_PORT, REDIS_HOST
from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy


class FirstAvailableOptimStrategy(FirstAvailableStrategy):
    """
    Provider‑selection strategy with host‑affinity optimisation.

    Extends :class:`FirstAvailableStrategy` by first trying to reuse the
    provider that was used most recently for the given model (if it is still
    free).  If that fails, it looks for any other free provider that already
    hosts the model before finally falling back to the standard first‑available
    behaviour.
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
    ) -> None:
        """
        Initialise the optimiser.  All arguments are passed straight through to
        :class:`FirstAvailableStrategy` – the defaults are the same as in the
        base class.
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
        )

        if clear_buffers:
            self._clear_buffers()

    # ----------------------------------------------------------------------
    # Overridden public API
    # ----------------------------------------------------------------------
    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict]:
        """
        Acquire a provider using the optimisation steps described in the
        module docstring.
        """
        # Initialise the Redis structures (identical to the base implementation).
        redis_key, is_random = self.init_provider(
            model_name=model_name, providers=providers, options=options
        )
        if not redis_key:
            return None

        # ------------------------------------------------------------------
        # Step 1 – Try to use the last host that handled this model.
        # ------------------------------------------------------------------
        last_host = self._retrieve_last_host(model_name)
        if last_host:
            for provider in providers:
                # Host identifier may be stored under different keys.
                provider_host = (
                    provider.get("host")
                    or provider.get("api_host")
                    or provider.get("id")
                )
                if provider_host != last_host:
                    continue

                provider_field = self._provider_field(provider)
                try:
                    ok = int(
                        self._acquire_script(keys=[redis_key], args=[provider_field])
                    )
                    if ok == 1:
                        provider["__chosen_field"] = provider_field
                        # Remember the host for the next request.
                        self._store_last_host(model_name, last_host)
                        return provider
                except Exception:
                    # Lua script error – continue, fallback will handle the rest.
                    pass

        # ------------------------------------------------------------------
        # Step 2 – Scan other hosts that already have the model loaded.
        # ------------------------------------------------------------------
        for provider in providers:
            provider_host = (
                provider.get("host")
                or provider.get("api_host")
                or provider.get("id")
            )
            # Skip the host we already checked above.
            if provider_host == last_host:
                continue

            provider_field = self._provider_field(provider)
            try:
                ok = int(
                    self._acquire_script(keys=[redis_key], args=[provider_field])
                )
                if ok == 1:
                    provider["__chosen_field"] = provider_field
                    # Remember the host that provided the model.
                    if provider_host:
                        self._store_last_host(model_name, provider_host)
                    return provider
            except Exception:
                # Not critical – keep looking.
                pass

        # ------------------------------------------------------------------
        # Step 3 – Find a provider that supports the model but doesn't have
        #          any model loaded yet. If one exists, select it.
        # ------------------------------------------------------------------
        for provider in providers:
            # Does the provider support the requested model?
            provider_models = provider.get("models") or [provider.get("model")]
            if model_name not in provider_models:
                continue

            # Skip providers that already have models loaded.
            if provider.get("loaded_models"):
                continue

            provider_field = self._provider_field(provider)
            try:
                ok = int(
                    self._acquire_script(keys=[redis_key], args=[provider_field])
                )
                if ok == 1:
                    provider["__chosen_field"] = provider_field
                    provider_host = (
                        provider.get("host")
                        or provider.get("api_host")
                        or provider.get("id")
                    )
                    if provider_host:
                        self._store_last_host(model_name, provider_host)
                    return provider
            except Exception:
                # Ignore failures – fallback will handle the rest.
                pass

        # ------------------------------------------------------------------
        # Step 4 – Fallback to the classic first‑available algorithm.
        # ------------------------------------------------------------------
        # Delegate to the base class implementation to maintain
        # existing timeout and retry handling.
        return super().get_provider(model_name, providers, options)

    # ----------------------------------------------------------------------
    # Helper methods specific to the optimisation
    # ----------------------------------------------------------------------
    def _clear_buffers(self) -> None:
        """
        Remove stale Redis keys that are specific to the optimisation layer.

        The base class ``RedisBasedStrategyInterface`` already provides a
        ``_clear_buffers`` method that resets the generic provider‑lock fields.
        This optimiser adds an additional per‑model key
        ``model:<model_name>:last_host`` that stores the host which last served
        the model.  ``clear_buffers`` deletes those keys for **all** known
        models, ensuring that no stale affinity information remains after a
        deployment or a manual reset.

        The method does **not** delete the generic provider lock hashes – they
        are handled by the parent ``_clear_buffers`` if a full reset is required.
        """
        try:
            active_models = self._api_model_config.active_models
            for _, model_names in active_models.items():
                for model_name in model_names:
                    last_host_key = self._last_host_key(model_name)
                    self.redis_client.delete(last_host_key)
        except Exception as exc:
            if self.logger:
                self.logger.warning(
                    f"[FirstAvailableOptimStrategy] Failed to clear last‑host buffers: {exc}"
                )

    def _last_host_key(self, model_name: str) -> str:
        """
        Redis key that stores the name of the host that handled the most recent
        request for *model_name*.
        """
        return f"{self._get_redis_key(model_name)}:last_host"

    def _store_last_host(self, model_name: str, host_name: str) -> None:
        """
        Persist the chosen host for *model_name*.
        """
        try:
            self.redis_client.set(self._last_host_key(model_name), host_name)
        except Exception:
            pass

    def _retrieve_last_host(self, model_name: str) -> Optional[str]:
        """
        Return the previously stored host for *model_name*, or ``None`` if the
        key does not exist.
        """
        try:
            raw = self.redis_client.get(self._last_host_key(model_name))
            return raw.decode() if raw else None
        except Exception:
            return None
