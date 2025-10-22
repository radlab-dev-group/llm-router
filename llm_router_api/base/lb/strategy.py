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
        Return a unique identifier for a provider configuration.

        The identifier is derived from fields that uniquely identify a
        provider (e.g., its name or endpoint).  Subclasses may rely on
        this key for caching the per ‑ provider state.
        """
        return provider_cfg.get("id") or provider_cfg.get("api_host", "unknown")

    @abstractmethod
    def choose(self, model_name: str, providers: List[Dict]) -> Dict:
        """
        Choose a provider for the given model.

        Parameters
        ----------
        model_name: str
            Name of the model for which a provider is required.
        providers: List[Dict]
            List of provider configuration dictionaries.

        Returns
        -------
        Dict
            The selected provider configuration.
        """
        raise NotImplementedError
