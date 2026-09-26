"""
Module providing ApiModelConfig for loading model configurations from a JSON file.
"""

import json

from typing import Any, Dict, List, Optional


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

    ACTIVE_MODELS_KEY = "active_models"
    FALLBACK_MODEL_KEY = "fallback_model"
    MODEL_PROVIDERS_KEY = "providers"

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
        self.safe_active_models_config = self._safe_active_models_configuration()

        self._validate_unique_identifiers()
        self._validate_fallback_models()

    def _try_to_load_config(self) -> Dict:
        """
        Load and parse the models config JSON file.

        Raises
        ------
        RuntimeError
            If the file cannot be parsed as valid JSON.
        """
        try:
            with open(self.models_config_path, "rt", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Invalid JSON format in models config file") from exc

    def _read_active_models(self) -> Dict[str, str]:
        """
        Read the JSON configuration and return a dictionary of active models.

        Returns:
            Dict[str, List[str]]: Mapping of model types to lists of active
            model names. Returns an empty dict if no models are defined.
        """
        models_config = self._try_to_load_config()
        if models_config:
            exists_model = False
            for _mtype, model_list in models_config.items():
                if model_list:
                    exists_model = True
                    break
            if not exists_model:
                return {}
        return models_config[self.ACTIVE_MODELS_KEY]

    def _active_models_configuration(self) -> Dict:
        """
        Build a dictionary containing the configuration for each active model.
        Now each model maps to a **list** of provider configurations.
        Returns:
            Dict[str, List[Dict]]: Mapping of model name to a list of provider dicts.
        """
        models_configuration: Dict[str, List[Dict]] = {}
        models_json = self._try_to_load_config()

        for m_type, models_list in self.active_models.items():
            for m_name in models_list:
                model_config = models_json[m_type][m_name]
                if self.MODEL_PROVIDERS_KEY not in model_config:
                    raise KeyError(f"{m_type}:{m_name} has no providers!")
                models_configuration[m_name] = model_config
        return models_configuration

    def _safe_active_models_configuration(self):
        """
        Build a safe copy of the active models configuration.
        Sensitive fields (``api_token``) are masked with an empty string,
        so the result can be safely used in logs or debug output.
        Returns:
            Dict[str, Dict]: Mapping of model name to a sanitized configuration dict.
        """
        return {
            name: {**cfg, "api_token": ""}
            for name, cfg in self.models_configs.items()
        }

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
            for provider in model_cfg.get(self.MODEL_PROVIDERS_KEY, []):
                pid = provider.get("id")
                if pid:
                    if pid in seen_ids:
                        duplicates.add(pid)
                    else:
                        seen_ids.add(pid)

        if duplicates:
            dup_str = ", ".join(sorted(duplicates))
            raise ValueError(f"Duplicate provider identifiers found: {dup_str}")

    @classmethod
    def fallback_model_of(cls, model_cfg: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Return the ``fallback_model`` declared by *model_cfg*.

        Parameters
        ----------
        model_cfg : Dict
            Configuration dictionary of a single model.  Anything that is not
            a non-blank string (missing key, ``None``, empty string) means
            “no fallback configured”.

        Returns
        -------
        Optional[str]
            The trimmed fallback model name, or ``None`` when the model does
            not declare one.
        """
        if not isinstance(model_cfg, dict):
            return None
        value = model_cfg.get(cls.FALLBACK_MODEL_KEY)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _validate_fallback_models(self) -> None:
        """
        Ensure every declared ``fallback_model`` can be safely followed.

        Two rules are enforced at load time so that the runtime fallback chain
        never has to guard against misconfiguration:

        * the target must be an active model known to the router;
        * the chain must be acyclic (a self reference is a cycle too).

        Raises
        ------
        ValueError
            If a ``fallback_model`` is not a string, points at an unknown
            model, or closes a reference cycle.  The message always contains
            the offending chain (``a -> b -> a``) for quick triage.
        """
        models = self.models_configs

        for name, cfg in models.items():
            raw = (
                cfg.get(ApiModelConfig.FALLBACK_MODEL_KEY)
                if isinstance(cfg, dict)
                else None
            )
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            if not isinstance(raw, str):
                raise ValueError(
                    f"Model '{name}' declares a non-string "
                    f"{ApiModelConfig.FALLBACK_MODEL_KEY}: {raw!r}"
                )

        for name in models:
            chain = [name]
            current = name
            while True:
                target = ApiModelConfig.fallback_model_of(models.get(current))
                if target is None:
                    break
                if target not in models:
                    raise ValueError(
                        f"Model '{name}' declares unknown "
                        f"{ApiModelConfig.FALLBACK_MODEL_KEY} '{target}'"
                    )
                if target in chain:
                    chain.append(target)
                    raise ValueError(
                        "Circular "
                        f"{ApiModelConfig.FALLBACK_MODEL_KEY} reference: "
                        f"{' -> '.join(chain)}"
                    )
                chain.append(target)
                current = target
