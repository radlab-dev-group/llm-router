"""
This module implements the :class:`~FirstAvailableStrategy`, a concrete
strategy for selecting the first available provider for a given model.  The
strategy coordinates provider selection across multiple processes using
Redis hashes as lightweight distributed locks.

The implementation relies on two Lua scripts registered with Redis:

* ``_acquire_script`` – atomically marks a provider as chosen if it is not
  currently taken.
* ``_release_script`` – releases the lock by deleting the provider field.

Both scripts treat a missing field or a field set to ``'false'`` as an
available provider.

Typical usage:

    strategy = FirstAvailableStrategy(models_config_path='dir/models-config.json')
    provider = strategy.get_provider('model-name', providers_list)
    # ... use the provider ...
    strategy.put_provider('model-name', provider)

"""

import time
import logging


try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from typing import List, Dict, Optional, Any

from llm_router_api.base.constants import REDIS_PORT, REDIS_HOST
from llm_router_api.base.lb.redis_strategy_i import RedisBasedStrategyI


class FirstAvailableStrategy(RedisBasedStrategyI):
    """
    Strategy that selects the first free provider for a model using Redis.

    The class inherits from
    :class:`~llm_router_api.base.lb.strategy.ChooseProviderStrategyI`
    and adds Redis‑based coordination.  It ensures that at most one consumer
    holds a particular provider at any time, even when multiple workers run
    concurrently on different hosts.

    Parameters are forwarded to the base class where appropriate, and Redis
    connection details can be customised via the constructor arguments.
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
        redis_keys_prefix: Optional[str] = "fa_",
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
            redis_keys_prefix=redis_keys_prefix or "fa_",
        )

    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict | None:
        """
        Acquire a provider for *model_name* from the supplied ``providers`` list.

        The method attempts to lock a provider using a Redis‑backed
        atomic Lua script.  If ``options`` contains ``{\"random_choice\": True}``,
        the selection is performed on a shuffled copy of ``providers``; otherwise
        providers are examined in the order they appear in the list.

        Parameters
        ----------
        model_name : str
            Identifier of the model for which a provider is required.
        providers : List[Dict]
            A list of provider configuration dictionaries.  Each dictionary must
            contain the information required by :meth:`_provider_field` to build a
            unique Redis hash field name.
        options : dict, optional
            Additional flags that influence the acquisition strategy.  Currently
            supported keys:
            ``random_choice`` (bool) – when ``True`` the provider is chosen at
            random; defaults to ``False``.

        Returns
        -------
        dict | None
            The chosen provider dictionary with an extra ``"__chosen_field"``
            entry indicating the Redis hash field that was locked.  Returns
            ``None`` if ``providers`` is empty.

        Raises
        ------
        TimeoutError
            Raised when no provider can be locked within the ``timeout`` period
            configured for the strategy instance.

        Notes
        -----
        * The method creates the Redis hash (``model:<model_name>``) and initial
          ``false`` fields if they do not already exist.
        * The lock is represented by the value ``'true'`` in the hash field.
        * Call :meth:`put_provider` to release the lock once the provider is no
          longer needed.
        """
        redis_key, is_random = self.init_get_provider(
            model_name=model_name, providers=providers, options=options
        )
        if not redis_key:
            return None

        # self._print_provider_status(redis_key, providers)

        return self._run_fa(
            model_name=model_name,
            redis_key=redis_key,
            is_random=is_random,
            set_last_host=False,
        )

    def _run_fa(
        self, model_name: str, redis_key: str, is_random: bool, set_last_host: bool
    ):
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
                    if set_last_host:
                        host_name = chosen.get("host") or chosen.get("server")
                        if host_name:
                            self._set_last_host(redis_key, host_name)
                    return chosen
            else:
                chosen = self._try_acquire_deterministic(redis_key, active)
                if chosen:
                    if set_last_host:
                        host_name = chosen.get("host") or chosen.get("server")
                        if host_name:
                            self._set_last_host(redis_key, host_name)
                    return chosen

            # Back‑off before the next attempt
            time.sleep(self.check_interval)
