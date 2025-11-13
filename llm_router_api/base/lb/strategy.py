import logging

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from llm_router_api.base.model_config import ApiModelConfig


class ChooseProviderStrategyI(ABC):
    REPLACE_PROVIDER_KEY = ["/", ":", "-", ".", ",", ";", " ", "\t", "\n"]

    """
    Abstract base for provider‑selection strategies.

    Concrete subclasses must implement :meth:`choose` which returns a
    provider configuration dictionary based on the supplied model name
    and the list of available providers.
    """

    def __init__(
        self, models_config_path: str, logger: Optional[logging.Logger]
    ) -> None:
        self._api_model_config = ApiModelConfig(
            models_config_path=models_config_path
        )
        self.logger = logger

    def __str__(self):
        return str(self.__class__.__name__)

    def _provider_key(self, provider_cfg: Dict) -> str:
        """
        Return a unique identifier for a provider configuration.

        The identifier is derived from fields that uniquely identify a
        provider (e.g., its name or endpoint).  Subclasses may rely on
        this key for caching the per ‑ provider state.
        """
        _pk = provider_cfg.get("id") or provider_cfg.get("api_host", "unknown")
        for ch in self.REPLACE_PROVIDER_KEY:
            _pk = _pk.replace(ch, "_")
        return _pk

    @abstractmethod
    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """
        Choose a provider for the given model.

        Parameters
        ----------
        model_name: str
            Name of the model for which a provider is required.
        providers: List[Dict]
            List of provider configuration dictionaries.
        options: Dict[str, Any], default: None
            Options passed to the chosen provider.

        Returns
        -------
        Dict
            The selected provider configuration.
        """
        raise NotImplementedError

    def put_provider(
        self,
        model_name: str,
        provider: Dict,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Notify the strategy that a provider has been used.

        This method is called after a provider has been selected and used,
        allowing the strategy to update its internal state (e.g., for
        tracking usage, updating metrics, or implementing feedback loops).

        The default implementation does nothing. Subclasses may override
        this method to implement stateful behavior such as round-robin
        rotation, failure tracking, or performance-based selection.

        Parameters
        ----------
        model_name : str
            Name of the model for which the provider was used.
        provider : Dict
            The provider configuration dictionary that was used.
        options: Dict[str, Any], default: None
            Options passed to the chosen provider.
        """
        pass
