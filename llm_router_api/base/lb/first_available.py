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

Typical usage::

    strategy = FirstAvailableStrategy(models_config_path='dir/models-config.json')
    provider = strategy.get_provider('model-name', providers_list)
    # ... use the provider ...
    strategy.put_provider('model-name', provider)

"""

import time
import logging
import random

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from typing import List, Dict, Optional, Any

from llm_router_api.base.constants import REDIS_PORT, REDIS_HOST
from llm_router_api.base.lb.provider_monitor import RedisProviderMonitor
from llm_router_api.base.lb.first_available_i import FirstAvailableStrategyI


class FirstAvailableStrategy(FirstAvailableStrategyI):
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
            strategy_prefix="fa_",
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

        redis_key, is_random = self.init_provider(
            model_name=model_name, providers=providers, options=options
        )
        if not redis_key:
            return None

        start_time = time.time()
        while True:
            _providers = self._get_active_providers(
                model_name=model_name, providers=providers
            )

            if not len(_providers):
                time.sleep(self.check_interval)

            if time.time() - start_time > self.timeout:
                raise TimeoutError(
                    f"No available provider found for model '{model_name}' "
                    f"within {self.timeout} seconds"
                )

            if is_random:
                provider = self._try_acquire_random_provider(
                    redis_key=redis_key, providers=_providers
                )
                if provider:
                    provider_field = self._provider_field(provider)
                    provider["__chosen_field"] = provider_field
                    return provider
            else:
                for provider in _providers:
                    provider_field = self._provider_field(provider)
                    try:
                        ok = int(
                            self._acquire_script(
                                keys=[redis_key], args=[provider_field]
                            )
                        )
                        if ok == 1:
                            provider["__chosen_field"] = provider_field
                            return provider
                    except Exception:
                        pass
            time.sleep(self.check_interval)

    def put_provider(
        self,
        model_name: str,
        provider: Dict,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Release a previously acquired provider back to the pool.

        The method removes the lock field from the Redis hash, making the
        provider available for subsequent ``get_provider`` calls.  It also
        cleans up the temporary ``"__chosen_field"`` entry from the provider
        dictionary.

        Parameters
        ----------
        model_name : str
            The model name associated with the provider.
        provider : Dict
            The provider dictionary that was returned by :meth:`get_provider`.
        options: Dict[str, Any], default: None
            Additional options passed to the chosen provider.
        """
        redis_key = self._get_redis_key(model_name)
        provider_field = self._provider_field(provider)
        try:
            self.redis_client.hdel(redis_key, provider_field)
        except Exception:
            raise

        provider.pop("__chosen_field", None)

    def _try_acquire_random_provider(
        self, redis_key: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Attempt to lock a provider chosen at random.

        The method works in three stages:

        1. **Shuffle** – a shallow copy of ``providers`` is shuffled so that each
           provider has an equal probability of being tried first.  The original
           list is left untouched.
        2. **Atomic acquisition** – each shuffled provider is passed to the
           ``_acquire_script`` Lua script which atomically sets the corresponding
           Redis hash field to ``'true'`` *only if* it is currently ``'false'`` or
           missing.  The first provider for which the script returns ``1`` is
           considered successfully acquired.
        3. **Fallback** – if none of the providers can be locked (e.g., all are
           currently in use), the method falls back to the *first* provider in the
           original ``providers`` list, marks its ``"__chosen_field"`` for
           consistency, and returns it.  This fallback mirrors the behaviour of
           the non‑random acquisition path and ensures the caller always receives
           a provider dictionary (or ``None`` when ``providers`` is empty).

        Parameters
        ----------
        redis_key : str
            The Redis hash key associated with the model (e.g., ``model:<name>``).
        providers : List[Dict]
            A list of provider configuration dictionaries.  Each dictionary must
            contain sufficient information for :meth:`_provider_field` to generate
            a unique field name within the Redis hash.

        Returns
        -------
        Optional[Dict]
            The selected provider dictionary with an additional ``"__chosen_field"``
            entry indicating the Redis hash field that was locked.  Returns ``None``
            only when the input ``providers`` list is empty.

        Raises
        ------
        Exception
            Propagates any unexpected exceptions raised by the Lua script execution;
            callers may catch these to implement retry or logging logic.

        Notes
        -----
        * The random selection is *non‑deterministic* on each call; however, the
          fallback to the first provider ensures deterministic behaviour when
          all providers are currently busy.
        * The method does **not** block; it returns immediately after trying all
          shuffled providers.
        """
        shuffled = providers[:]
        random.shuffle(shuffled)
        for provider in shuffled:
            provider_field = self._provider_field(provider)
            try:
                ok = int(
                    self._acquire_script(keys=[redis_key], args=[provider_field])
                )
                if ok == 1:
                    provider["__chosen_field"] = provider_field
                    return provider
            except Exception:
                continue
        return None

    def _get_active_providers(
        self, model_name: str, providers: List[Dict]
    ) -> List[Dict]:
        active_providers = self._monitor.get_providers(
            model_name=model_name, only_active=True
        )
        return active_providers
