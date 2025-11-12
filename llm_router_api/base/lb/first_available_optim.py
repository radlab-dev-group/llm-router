from __future__ import annotations

import time

from typing import Any, Dict, List, Optional

from llm_router_api.base.lb.redis_strategy_i import RedisBasedStrategyI


class FirstAvailableOptimStrategy(RedisBasedStrategyI):
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
        redis_key, is_random = self.init_get_provider(
            model_name=model_name, providers=providers, options=options
        )
        if not redis_key:
            return None

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
