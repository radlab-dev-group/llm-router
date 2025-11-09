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
import random

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from typing import List, Dict, Optional, Any

from llm_router_api.base.constants import REDIS_PORT, REDIS_HOST
from llm_router_api.base.lb.strategy import ChooseProviderStrategyI
from llm_router_api.base.lb.provider_monitor import RedisProviderMonitor


class FirstAvailableStrategy(ChooseProviderStrategyI):
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
        if not REDIS_IS_AVAILABLE:
            raise RuntimeError("Redis is not available. Please install it first.")

        super().__init__(models_config_path=models_config_path)

        self.redis_client = redis.Redis(
            host=redis_host, port=redis_port, db=redis_db, decode_responses=True
        )
        self.timeout = timeout
        self.check_interval = check_interval

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

        # Start providers monitor
        self._monitor = RedisProviderMonitor(
            redis_client=self.redis_client,
            check_interval=5.0,
            clear_buffers=clear_buffers,
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
        if not providers:
            return None

        # Register providers for monitoring (only once per model)
        self._monitor.add_providers(model_name, providers)

        redis_key = self._get_redis_key(model_name)
        start_time = time.time()

        # Ensure fields exist; if someone removed the hash, recreate it
        if not self.redis_client.exists(redis_key):
            for p in providers:
                self.redis_client.hset(redis_key, self._provider_field(p), "false")

        # self._print_provider_status(redis_key, providers)

        is_random = options and options.get("random_choice", False)

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

    def _get_redis_key(self, model_name: str) -> str:
        """
        Return Redis key prefix for a given model.
        """
        for ch in self.REPLACE_PROVIDER_KEY:
            model_name = model_name.replace(ch, "_")
        return f"model:{model_name}"

    def _provider_field(self, provider: dict) -> str:
        """
        Build the Redis hash field name that stores the chosen flag
        for a given provider.

        Parameters
        ----------
        provider : dict
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
            provider_id = provider.get("id") or provider.get("name") or field
            print(f"{icon}  {provider_id:<30} [{field}]")
        print("-" * 40)
