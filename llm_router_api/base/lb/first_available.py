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
    First Available Strategy using Redis for distributed provider state management.

    This strategy maintains provider availability status in Redis and selects
    the first available provider. Multiple processes can safely access this
    strategy simultaneously thanks to Redis-backed synchronization.

    For each model, providers are stored in Redis with the format:
    {model_name}:{provider_id} -> {"is_chosen": bool}

    When get_provider is called, it marks a provider as unavailable (is_chosen=True).
    When put_provider is called, it marks a provider as available again (is_chosen=False).
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
        """
        Get the first available provider for the model.

        This method:
        1. Initializes provider status in Redis on first use.
        2. Waits for an available provider (one with is_chosen=False).
        3. Marks the selected provider as unavailable (is_chosen=True).
        4. Returns the provider configuration.

        Blocks with polling if no providers are available, up to the timeout.

        Parameters
        ----------
        model_name : str
            The model name.
        providers : List[Dict]
            List of provider configurations.

        Returns
        -------
        Dict
            The first available provider configuration.

        Raises
        ------
        TimeoutError
            If no available provider is found within the timeout period.
        ValueError
            If the provider list is empty.
        """
        if not providers:
            raise ValueError(f"No providers configured for model '{model_name}'")

        # Initialize providers on first use
        # self._initialize_providers(model_name, providers)

        redis_key = self._get_redis_key(model_name)
        start_time = time.time()

        while True:
            print("?", providers)
            if time.time() - start_time > self.timeout:
                raise TimeoutError(
                    f"No available provider found for model '{model_name}' "
                    f"within {self.timeout} seconds"
                )

            # Try to find an available provider
            for provider in providers:
                provider_id = self._provider_key(provider)
                provider_field = f"{provider_id}:is_chosen"

                # Atomically check and set the provider as chosen
                # Use Redis pipeline for atomic operation
                pipe = self.redis_client.pipeline()
                try:
                    pipe.watch(redis_key)
                    is_chosen = self.redis_client.hget(redis_key, provider_field)

                    if is_chosen == "false":
                        # Provider is available, mark it as chosen
                        pipe.multi()
                        pipe.hset(redis_key, provider_field, "true")
                        pipe.execute()
                        return provider

                except redis.WatchError:
                    continue
                finally:
                    pipe.reset()

            # No available provider found, wait and retry
            time.sleep(self.check_interval)

    def put_provider(self, model_name: str, provider: Dict) -> None:
        """
        Mark a provider as available again after use.

        This method marks the provider as available (is_chosen=False) so it can
        be selected by other waiting processes.

        Parameters
        ----------
        model_name : str
            The model name.
        provider : Dict
            The provider configuration dictionary that was used.
        """
        redis_key = self._get_redis_key(model_name)
        provider_id = self._provider_key(provider)
        provider_field = f"{provider_id}:is_chosen"

        # Mark provider as available
        self.redis_client.hset(redis_key, provider_field, "false")
