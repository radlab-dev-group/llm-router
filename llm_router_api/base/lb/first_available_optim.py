from __future__ import annotations

import logging

from typing import Any, Dict, List, Optional

from llm_router_api.base.constants import REDIS_PORT, REDIS_HOST
from llm_router_api.base.lb.first_available import FirstAvailableStrategy


class FirstAvailableOptimStrategy(FirstAvailableStrategy):
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
        timeout : int, optional
            Maximum time (in seconds) to wait for an available provider.
            Default is ``60``.
        check_interval : float, optional
            Time to sleep between checks for available providers (in seconds).
            Default is ``0.1``.
        clear_buffers:
            Whether to clear all buffers when starting. Default is ``True``.
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
            redis_keys_prefix=redis_keys_prefix or "fa_optim_",
        )

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

        return self._run_fa(
            model_name=model_name,
            redis_key=redis_key,
            is_random=is_random,
            set_last_host=True,
        )
