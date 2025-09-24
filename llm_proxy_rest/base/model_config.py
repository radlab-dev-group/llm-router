"""
Module providing ApiModelConfig for loading model configurations from a JSON file.
"""

import json
from typing import Dict


class ApiModelConfig:
    """Configuration loader for API models defined in a JSON file.

    Attributes
        ----------
        models_config_path : str
            The provided path, stored for later use.
        active_models : Dict[str, List[str]]
            Mapping of model type to a list of active model names extracted
            from the ``active_models`` key of the JSON file.
        models_configs : Dict[str, Dict]
            Full configuration dictionaries for each active model, built by
            :meth:`_active_models_configuration`.
    """

    def __init__(self, models_config_path: str):
        """
        Initialise an :class:`ApiModelConfig` instance.

        Parameters
        ----------
        models_config_path : str
            Filesystem path to a JSON configuration file that defines
            ``active_models`` and model‑type specific configurations.

        Raises
        ------
        FileNotFoundError
            If ``models_config_path`` does not exist.
        json.JSONDecodeError
            If the file content is not valid JSON.
        KeyError
            If the expected ``active_models`` key is missing.
        """
        self.models_config_path = models_config_path

        self.active_models = self._read_active_models()
        self.models_configs = self._active_models_configuration()

    def _read_active_models(self) -> Dict[str, str]:
        """
        Read the JSON configuration and return a dictionary of active models.

        Returns:
            Dict[str, List[str]]: Mapping of model types to lists of active
            model names. Returns an empty dict if no models are defined.
        """
        models_config = json.load(open(self.models_config_path, "rt"))
        if len(models_config):
            exists_model = False
            for model_type, model_list in models_config.items():
                if len(model_list):
                    exists_model = True
                    break
            if not exists_model:
                return {}
        return models_config["active_models"]

    def _active_models_configuration(self) -> Dict:
        """
        Build a dictionary containing the configuration for each active model.

        Returns:
            Dict[str, Dict]: Mapping of model name to its configuration dictionary.
        """
        models_configuration = {}
        models_json = json.load(open(self.models_config_path, "rt"))
        for m_type, models_list in self.active_models.items():
            for m_name in models_list:
                models_configuration[m_name] = models_json[m_type][m_name]
        return models_configuration
