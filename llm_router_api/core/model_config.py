"""
Module providing ApiModelConfig for loading model configurations from a JSON file.
"""

import json
from typing import Dict, List


class ApiModelConfig:
    """
    Configuration loader for API models defined in a JSON file.

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

        self._validate_unique_identifiers()

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
        Now each model maps to a **list** of provider configurations.
        Returns:
            Dict[str, List[Dict]]: Mapping of model name to a list of provider dicts.
        """
        models_configuration: Dict[str, List[Dict]] = {}
        models_json = json.load(open(self.models_config_path, "rt"))
        for m_type, models_list in self.active_models.items():
            for m_name in models_list:
                model_config = models_json[m_type][m_name]
                if "providers" not in model_config:
                    raise KeyError(f"{m_type}:{m_name} has no providers!")
                models_configuration[m_name] = model_config
        return models_configuration

    def _validate_unique_identifiers(self) -> None:
        """
        Ensure that every provider ``id`` across all active models is unique.
        Checks both ``providers`` and ``providers_sleep`` sections.

        Raises
        ------
        ValueError
            If any provider ``id`` is duplicated.
        """
        seen_ids = set()
        duplicates = set()

        for model_cfg in self.models_configs.values():
            # Check the main providers list
            for provider in model_cfg.get("providers", []):
                pid = provider.get("id")
                if pid:
                    if pid in seen_ids:
                        duplicates.add(pid)
                    else:
                        seen_ids.add(pid)

        if duplicates:
            dup_str = ", ".join(sorted(duplicates))
            raise ValueError(f"Duplicate provider identifiers found: {dup_str}")
