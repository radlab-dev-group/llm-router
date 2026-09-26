"""
Model utilities.

This module defines:
- ApiModel: an immutable representation of a single model loaded from configuration.
- ModelHandler: a lightweight manager that loads model configuration and exposes
  helpers to retrieve individual model definitions.

A model may declare a ``fallback_model``.  When no provider can serve the
requested model (no providers configured, no healthy provider, or every
provider busy until the strategy timeout) the handler walks the
``model -> fallback_model -> ...`` chain and asks the load-balancing strategy
for a provider of the next model, so the fallback provider is chosen by the
very same balancing rules.
"""

import logging

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from llm_router_api.core.model_config import ApiModelConfig
from llm_router_api.core.lb.provider_strategy_facade import ProviderStrategyFacade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiModel:
    """
    Immutable representation of a single model defined in configuration.

    Attributes
    ----------
    name : str
        Unique model identifier (e.g., "google/gemma-3-12b-it").
    api_host : str
        API host used to call the model.
    api_type : str
        External api type: llama, vllm, openapi
    api_token : str
        Authorization token (maybe empty if not required).
    input_size : int
        Maximum supported input size for the model.
    model_path : str
        Optional path to model (in case when local model is used)
    keep_alive : str
        Optional keep alive (time in s or m or h) model
    """

    id: str
    name: str
    api_host: str
    api_type: str
    api_token: str
    input_size: int
    model_path: Optional[str] = None
    keep_alive: Optional[str] = None
    tool_calling: Optional[bool] = False
    is_embedding: Optional[bool] = False
    lease: Optional[str] = None

    @staticmethod
    def from_config(name: str, cfg: Dict) -> "ApiModel":
        """
        Build an ApiModel instance from a single model configuration entry.

        Parameters
        ----------
        name : str
            Model name.
        cfg : Dict
            Configuration dictionary for one model containing keys like
            "api_host", "api_token", and "input_size".

        Returns
        -------
        ApiModel
            Constructed model object.

        Notes
        -----
        The "input_size" value can be an integer or a numeric string;
        it will be converted to an int. If conversion fails, defaults to 0.
        """
        return ApiModel(
            id=str(cfg["id"]),
            name=name,
            api_host=str(cfg["api_host"]),
            api_type=str(cfg["api_type"]),
            api_token=str(cfg.get("api_token", "")),
            input_size=int(cfg.get("input_size", 0)),
            model_path=str(cfg.get("model_path", "")),
            keep_alive=str(cfg.get("keep_alive", "")),
            tool_calling=bool(cfg.get("tool_calling", False)),
            is_embedding=bool(cfg.get("is_embedding", False)),
            # Transient worker-slot lease handed over by the load-balancing
            # strategy; it has to survive the round trip through ``as_dict()``
            # so ``put_provider`` can release exactly this slot.
            lease=cfg.get("__lease"),
        )

    def as_dict(self) -> Dict[str, Any]:
        """
        Return the configuration as a dictionary.

        Returns
        -------
        Dict[str, Any]
            Dictionary representation of this ApiModelConfig instance.
        """
        config = {
            "id": self.id,
            "name": self.name,
            "api_host": self.api_host,
            "api_type": self.api_type,
            "api_token": self.api_token,
            "input_size": self.input_size,
            "model_path": self.model_path,
            "keep_alive": self.keep_alive,
            "tool_calling": self.tool_calling,
            "is_embedding": self.is_embedding,
        }
        # Carried back to the strategy that acquired it; omitted when there is
        # no lease so the dictionary keeps its historical shape.
        if self.lease:
            config["__lease"] = self.lease
        return config


class ModelHandler:
    """
    Lightweight model manager backed by a JSON configuration file.

    On construction, it initializes an ApiModelConfig loader and provides
    helpers to fetch individual model definitions.

    Parameters
    ----------
    models_config_path : str
        Filesystem path to the JSON configuration file.

    Attributes
    ----------
    api_model_config : ApiModelConfig
        Loader responsible for reading and exposing model configuration.
    """

    LIST_MODEL_FIELDS_REMOVE = ["model_path", "api_token"]

    def __init__(
        self, models_config_path: str, provider_chooser: ProviderStrategyFacade
    ):
        """
        Initialize the handler with the provided configuration path.

        Parameters
        ----------
        models_config_path : str
            Path to the JSON configuration file containing model definitions.
        """
        self.provider_chooser = provider_chooser
        self.api_model_config: ApiModelConfig = ApiModelConfig(models_config_path)

    def get_model_provider(
        self,
        model_name: str,
        options: Optional[Dict[str, Any]] = None,
        fake: bool = False,
    ) -> Optional[ApiModel]:
        """
        Return a model definition for the given name.

        The provider is selected by the configured load-balancing strategy.
        When the requested model cannot be served — it has no providers, the
        health monitor reports none of them usable, or every provider stays
        busy until the strategy timeout — the handler walks the declared
        ``fallback_model`` chain and lets the strategy pick a provider of the
        next model.  The returned :class:`ApiModel` always carries the name of
        the model that actually serves the request, which is also the key used
        later by :meth:`put_model_provider` to release the provider.

        Parameters
        ----------
        model_name : str
            Model identifier present among active models.
        options: Dict[str, Any] Default is None
            Options passed to strategy
        fake: bool, Default is False
            If True, return a 'fake' provider model without allocating resources

        Returns
        -------
        Optional[ApiModel]
            ApiModel instance if found; otherwise, None.

        Raises
        ------
        KeyError
            If *model_name* is not an active model.
        TimeoutError
            If no provider could be acquired for the last model of the
            fallback chain within the strategy timeout.
        """
        models_configs = self.api_model_config.models_configs
        if model_name not in models_configs:
            # Unknown models keep failing loudly (unchanged behaviour).
            raise KeyError(model_name)

        chain = self._fallback_chain(model_name)
        last_index = len(chain) - 1

        for index, hop in enumerate(chain):
            is_last_hop = index == last_index
            providers = self._providers_of(hop)

            if not providers:
                if is_last_hop:
                    self._log_chain_failure(chain, "no providers configured")
                    return None
                self._log_fallback(hop, chain[index + 1], "no providers configured")
                continue

            if fake:
                return ApiModel.from_config(hop, providers[0])

            # Skip a hop that is known (health data) to be unable to serve,
            # instead of waiting for the strategy selection timeout.
            if (
                not is_last_hop
                and self.provider_chooser.has_available_provider(
                    model_name=hop, providers=providers
                )
                is False
            ):
                self._log_fallback(hop, chain[index + 1], "no healthy provider")
                continue

            try:
                model_host_cfg = self.provider_chooser.get_provider(
                    model_name=hop, providers=providers, options=options
                )
            except TimeoutError:
                if is_last_hop:
                    self._log_chain_failure(chain, "selection timeout")
                    raise
                self._log_fallback(hop, chain[index + 1], "all providers busy")
                continue

            if model_host_cfg is None:
                if is_last_hop:
                    self._log_chain_failure(chain, "strategy returned no provider")
                    return None
                self._log_fallback(
                    hop, chain[index + 1], "strategy returned no provider"
                )
                continue

            if index > 0:
                self._record_model_fallback(model_name, hop)
                self._warn_if_smaller_context(model_name, hop, model_host_cfg)

            return ApiModel.from_config(hop, model_host_cfg)

        return None

    def _fallback_chain(self, model_name: str) -> List[str]:
        """
        Build the ``model -> fallback_model -> …`` chain for *model_name*.

        The chain always starts with the requested model and ends with the last
        model that declares no fallback of its own.  ``ApiModelConfig`` rejects
        unknown targets and cycles at load time, so the loop below can only
        terminate; the extra guards keep a hand‑built (unvalidated)
        configuration from looping forever.

        Parameters
        ----------
        model_name : str
            Model requested by the client.

        Returns
        -------
        List[str]
            Ordered model names to try, most preferred first.
        """
        models_configs = self.api_model_config.models_configs
        chain = [model_name]
        current = model_name

        while True:
            target = ApiModelConfig.fallback_model_of(models_configs.get(current))
            if target is None or target not in models_configs or target in chain:
                break
            chain.append(target)
            current = target

        return chain

    def _providers_of(self, model_name: str) -> List[Dict[str, Any]]:
        """Return the configured providers of *model_name* (empty if none)."""
        model_cfg = self.api_model_config.models_configs.get(model_name)
        if not model_cfg:
            return []
        return model_cfg.get("providers", []) or []

    def _record_model_fallback(self, model_name: str, fallback_model: str) -> None:
        """Count a request served by *fallback_model* instead of *model_name*."""
        recorder = getattr(self.provider_chooser, "record_model_fallback", None)
        if recorder is None:
            return
        recorder(model_name=model_name, fallback_model=fallback_model)

    def _warn_if_smaller_context(
        self, model_name: str, fallback_model: str, provider: Dict[str, Any]
    ) -> None:
        """Warn when the fallback provider has a smaller context window."""
        requested_sizes = [
            self._as_int(p.get("input_size")) for p in self._providers_of(model_name)
        ]
        requested_size = max(requested_sizes, default=0)
        fallback_size = self._as_int(provider.get("input_size"))

        if requested_size and fallback_size and fallback_size < requested_size:
            logger.warning(
                "Fallback model '%s' has a smaller context (%s tokens) than "
                "the requested model '%s' (%s tokens)",
                fallback_model,
                fallback_size,
                model_name,
                requested_size,
            )

    @staticmethod
    def _as_int(value: Any) -> int:
        """Best-effort integer conversion used for ``input_size`` comparisons."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _log_fallback(from_model: str, to_model: str, reason: str) -> None:
        """Log the switch from *from_model* to its fallback."""
        logger.warning(
            "No available provider for model '%s' (%s) - "
            "falling back to model '%s'",
            from_model,
            reason,
            to_model,
        )

    @staticmethod
    def _log_chain_failure(chain: List[str], reason: str) -> None:
        """Log that the whole fallback chain failed to provide a provider."""
        models = f"'{chain[0]}'"
        if len(chain) > 1:
            models = f"{models} (fallback chain: {' -> '.join(chain)})"
        logger.error("No provider available for model %s: %s", models, reason)

    def put_model_provider(
        self,
        model_name: str,
        provider: dict,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Set ``is_chosen`` flag of the given provider to ``False`` and update the
        stored providers list for the specified model.

        Parameters
        ----------
        model_name : str
            Name of the model whose provider list should be updated.
        provider : Dict
            Provider dictionary (as stored in the configuration) that should be
            un‑selected.  The dictionary must contain either an ``id`` key or a
            ``host`` key that uniquely identifies the provider.
        options: Dict[str, Any] Default is None
            Options passed to strategy

        Notes
        -----
        The operation is performed under a thread‑safe lock because multiple
        threads may read or modify the provider list concurrently.
        """
        self.provider_chooser.put_provider(
            model_name=model_name, provider=provider, options=options
        )

    def list_active_models(self) -> Dict[str, Any]:
        """
        List active models grouped by type.

        Returns
        -------
        Dict[str, Any]
            Mapping of a model type to a list of model dicts. Example:
            {
                "openapi": [{"name": "...", ...}, ...],
                "llama": [...]
            }
        """
        result: Dict[str, Any] = {}
        models_configs = self.api_model_config.models_configs
        for m_type, names in self.api_model_config.active_models.items():
            models = []
            for name in names:
                _p = models_configs[name].get("providers", [])
                if not _p:
                    continue

                model = _p[0].copy()
                for _r in self.LIST_MODEL_FIELDS_REMOVE:
                    if _r in model:
                        model.pop(_r)

                model["name"] = name
                models.append(model)
            result[m_type] = models
        return result
