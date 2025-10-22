from typing import List, Dict
from abc import ABC, abstractmethod


class ChooseProviderStrategyI(ABC):
    """
    Abstract base for provider‑selection strategies.

    Concrete subclasses must implement :meth:`choose` which returns a
    provider configuration dictionary based on the supplied model name
    and the list of available providers.
    """

    @staticmethod
    def _provider_key(provider_cfg: Dict) -> str:
        """
        Return a deterministic string key for a provider configuration.

        The key is used to store per‑provider state such as usage counters
        or latency histories.
        """
        return provider_cfg.get("id") or provider_cfg.get("api_host", "unknown")

    @abstractmethod
    def choose(self, model_name: str, providers: List[Dict]) -> Dict:
        """
        Select a provider for *model_name* from *providers*.

        Implementations may use static weights, dynamic metrics, or any
        other heuristic.  The returned dictionary must be one of the
        elements from *providers*.
        """
        raise NotImplementedError
