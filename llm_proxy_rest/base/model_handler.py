"""
Model utilities.

This module defines:
- ApiModel: an immutable representation of a single model loaded from configuration.
- ModelHandler: a lightweight manager that loads model configuration and exposes
  helpers to retrieve individual model definitions.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Any

from llm_proxy_rest.base.model_config import ApiModelConfig


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
        raw_size = cfg.get("input_size", 0)
        try:
            input_size = int(raw_size)
        except (TypeError, ValueError):
            input_size = 0

        return ApiModel(
            name=name,
            api_host=str(cfg.get("api_host", "")),
            api_type=str(cfg.get("api_type")),
            api_token=str(cfg.get("api_token", "")),
            input_size=input_size,
            model_path=str(cfg.get("api_token", "")),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
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

    def __init__(self, models_config_path: str):
        """
        Initialize the handler with the provided configuration path.

        Parameters
        ----------
        models_config_path : str
            Path to the JSON configuration file containing model definitions.
        """
        self.api_model_config: ApiModelConfig = ApiModelConfig(models_config_path)

    def get_model(self, model_name: str) -> Optional[ApiModel]:
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
        cfg = self.api_model_config.models_configs.get(model_name)
        if cfg is None:
            return None
        return ApiModel.from_config(model_name, cfg)
