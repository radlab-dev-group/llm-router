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

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from typing import List, Dict

from llm_router_api.base.lb.strategy import ChooseProviderStrategyI


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
        redis_host: str = "192.168.100.67",
        redis_port: int = 6379,
        redis_db: int = 0,
        timeout: int = 60,
        check_interval: float = 0.1,
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

        self._clear_buffers()

    def get_provider(self, model_name: str, providers: List[Dict]) -> Dict:
        """
        Acquire the first available provider for *model_name*.

        The method repeatedly attempts to acquire a lock on each provider in the
        order supplied by *providers*.  If a provider is successfully marked as
        chosen in Redis, the provider dictionary is returned with an additional
        ``"__chosen_field"`` entry that records the Redis hash field used for the
        lock.  The call blocks until a provider is obtained or *self.timeout*
        seconds have elapsed, in which case a :class:`TimeoutError` is raised.

        Parameters
        ----------
        model_name : str
            The name of the model for which a provider is required.
        providers : List[Dict]
            A list of provider configuration dictionaries.

        Returns
        -------
        Dict
            The selected provider configuration, augmented with a
            ``"__chosen_field"`` key.

        Raises
        ------
        TimeoutError
            If no provider becomes available within the configured timeout.
        RuntimeError
            If Redis is not available.
        """
        redis_key = self._get_redis_key(model_name)
        start_time = time.time()

        # Ensure fields exist; if someone removed the hash, recreate it
        if not self.redis_client.exists(redis_key):
            for p in providers:
                self.redis_client.hset(redis_key, self._provider_field(p), "false")

        while True:
            if time.time() - start_time > self.timeout:
                raise TimeoutError(
                    f"No available provider found for model '{model_name}' "
                    f"within {self.timeout} seconds"
                )

            for provider in providers:
                provider_field = self._provider_field(provider)
                try:
                    ok = int(
                        self._acquire_script(keys=[redis_key], args=[provider_field])
                    )
                    if ok == 1:
                        provider["__chosen_field"] = provider_field
                        return provider
                except Exception:
                    time.sleep(self.check_interval)
                    continue

            time.sleep(self.check_interval)

    def put_provider(self, model_name: str, provider: Dict) -> None:
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
        """
        redis_key = self._get_redis_key(model_name)
        provider_field = provider.get("__chosen_field")
        if provider_field is None:
            provider_field = self._provider_field(provider)

        try:
            self.redis_client.hdel(redis_key, provider_field)
        except Exception:
            raise

        provider.pop("__chosen_field", None)

    @staticmethod
    def _get_redis_key(model_name: str) -> str:
        """
        Return Redis key prefix for a given model.
        """
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

                init_flag = self._init_flag(model_name)
                self.redis_client.delete(init_flag)

                providers = models_configs[model_name]["providers"]
                for provider in providers:
                    provider_field = self._provider_field(provider)
                    self.redis_client.hset(redis_key, provider_field, "false")

                self._initialize_providers(
                    model_name=model_name, providers=providers
                )
