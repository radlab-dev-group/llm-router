import time

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from typing import List, Dict

from llm_router_api.base.lb.strategy import ChooseProviderStrategyI


class FirstAvailableStrategy(ChooseProviderStrategyI):

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
            Redis server host. Default is "localhost".
        redis_port : int, optional
            Redis server port. Default is 6379.
        redis_db : int, optional
            Redis database number. Default is 0.
        timeout : int, optional
            Maximum time (in seconds) to wait for an available provider. Default is 60.
        check_interval : float, optional
            Time to sleep between checks for available providers (in seconds). Default is 0.1.
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

    @staticmethod
    def _get_redis_key(model_name: str) -> str:
        """
        Get the Redis key prefix for storing provider status for a model.

        Parameters
        ----------
        model_name : str
            The model name.

        Returns
        -------
        str
            Redis key prefix in format "model:{model_name}".
        """
        return f"model:{model_name}"

    def _initialize_providers(self, model_name: str, providers: List[Dict]) -> None:
        """
        Initialize provider status in Redis if not already done.

        This method is called on the first use of get_provider for a given model.
        All providers are initially marked as available (is_chosen=False).

        Parameters
        ----------
        model_name : str
            The model name.
        providers : List[Dict]
            List of provider configurations.
        """
        redis_key = self._get_redis_key(model_name)

        # Check if already initialized using a flag
        init_flag = f"{redis_key}:initialized"
        if self.redis_client.exists(init_flag):
            return

        # Initialize all providers as available
        for provider in providers:
            provider_id = self._provider_key(provider)
            provider_field = f"{provider_id}:is_chosen"
            self.redis_client.hset(redis_key, provider_field, "false")

        # Set initialization flag
        self.redis_client.set(init_flag, "1")

    def _clear_buffers(self) -> None:
        active_models = self._api_model_config.active_models
        models_configs = self._api_model_config.models_configs
        for _, models_names in active_models.items():
            for model_name in models_names:
                redis_key = self._get_redis_key(model_name)

                init_flag = f"{redis_key}:initialized"
                self.redis_client.delete(init_flag)

                providers = models_configs[model_name]["providers"]
                for provider in providers:
                    provider_id = self._provider_key(provider)
                    provider_field = f"{provider_id}:is_chosen"
                    self.redis_client.hset(redis_key, provider_field, "false")

                self._initialize_providers(
                    model_name=model_name, providers=providers
                )

    def get_provider(self, model_name: str, providers: List[Dict]) -> Dict:
        # ... existing code up to redis_key/start_time ...

        redis_key = self._get_redis_key(model_name)
        start_time = time.time()

        # Ensure fields exist; if someone removed the hash, recreate it
        if not self.redis_client.exists(redis_key):
            for p in providers:
                pid = self._provider_key(p)
                self.redis_client.hset(redis_key, f"{pid}:is_chosen", "false")

        while True:
            if time.time() - start_time > self.timeout:
                raise TimeoutError(
                    f"No available provider found for model '{model_name}' "
                    f"within {self.timeout} seconds"
                )

            for provider in providers:
                provider_id = self._provider_key(provider)
                provider_field = f"{provider_id}:is_chosen"
                try:
                    ok = int(
                        self._acquire_script(keys=[redis_key], args=[provider_field])
                    )
                    if ok == 1:
                        # **Store the exact field name inside the dict** so that
                        # `put_provider` can release the same key even if the dict
                        # is later mutated.
                        provider["__chosen_field"] = provider_field
                        return provider
                except Exception:
                    time.sleep(self.check_interval)
                    continue

            time.sleep(self.check_interval)

    def put_provider(self, model_name: str, provider: Dict) -> None:
        redis_key = self._get_redis_key(model_name)
        provider_field = provider.get("__chosen_field")
        if provider_field is None:
            provider_id = self._provider_key(provider)
            provider_field = f"{provider_id}:is_chosen"

        try:
            self.redis_client.hdel(redis_key, provider_field)
        except Exception:
            raise

        provider.pop("__chosen_field", None)
