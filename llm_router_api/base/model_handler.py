"""
Model utilities.

This module defines:
- ApiModel: an immutable representation of a single model loaded from configuration.
- ModelHandler: a lightweight manager that loads model configuration and exposes
  helpers to retrieve individual model definitions.
"""

import threading

from dataclasses import dataclass
from typing import Dict, Optional, Any

from llm_router_api.base.lb.chooser import ProviderChooser
from llm_router_api.base.model_config import ApiModelConfig


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
    """

    id: str
    name: str
    api_host: str
    api_type: str
    api_token: str
    input_size: int
    model_path: Optional[str] = None

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
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "api_host": self.api_host,
            "api_type": self.api_type,
            "api_token": self.api_token,
            "input_size": self.input_size,
            "model_path": self.model_path,
        }


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

    def __init__(self, models_config_path: str, provider_chooser: ProviderChooser):
        """
        Initialize the handler with the provided configuration path.

        Parameters
        ----------
        models_config_path : str
            Path to the JSON configuration file containing model definitions.
        """
        self.provider_chooser = provider_chooser
        self.api_model_config: ApiModelConfig = ApiModelConfig(models_config_path)

        self._lock = threading.Lock()

    def get_model_provider(self, model_name: str) -> Optional[ApiModel]:
        """
        Return a model definition for the given name.

        Parameters
        ----------
        model_name : str
            Model identifier present among active models.

        Returns
        -------
        Optional[ApiModel]
            ApiModel instance if found; otherwise, None.
        """
        model_host_cfg = None
        with self._lock:
            providers = self.api_model_config.models_configs[model_name].get(
                "providers", []
            )

            model_host_cfg = self.provider_chooser.get_provider(
                model_name=model_name, providers=providers
            )

        if model_host_cfg is None:
            return None

        return ApiModel.from_config(model_name, model_host_cfg)

    def put_model_provider(self, model_name: str, provider: dict) -> None:
        """
        Set ``is_chosen`` flag of the given provider to ``False`` and update the
        stored providers list for the specified model.

        Parameters
        ----------
        model_name : str
            Name of the model whose provider list should be updated.
        provider : dict
            Provider dictionary (as stored in the configuration) that should be
            un‑selected.  The dictionary must contain either an ``id`` key or a
            ``host`` key that uniquely identifies the provider.

        Notes
        -----
        The operation is performed under a thread‑safe lock because multiple
        threads may read or modify the provider list concurrently.
        """
        with self._lock:
            self.provider_chooser.put_provider(
                model_name=model_name, provider=provider
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
                if not len(_p):
                    continue

                model = _p[0].copy()
                for _r in self.LIST_MODEL_FIELDS_REMOVE:
                    if _r in model:
                        model.pop(_r)

                model["name"] = name
                models.append(model)
            result[m_type] = models
        return result
