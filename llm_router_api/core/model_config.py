"""
Module providing ApiModelConfig for loading model configurations from any ConfigSource.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from llm_router_api.core.config_store.interface import ConfigSourceI, ConfigState


logger = logging.getLogger(__name__)


class ApiModelConfig:
    """
    Configuration loader for API models from a ConfigSource.

    Unlike the original version that loaded from a file once at init, this
    variant registers as a listener on the source's change notifications so
    that all instances observe updates atomically.

    Parameters
    ----------
    source : ConfigSourceI
        The configuration source providing the config data.
    logger : Optional[logging.Logger], optional
        Optional explicit logger; defaults to module-level logger.
    """

    def __init__(
        self,
        source: ConfigSourceI,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._source = source
        self._state: ConfigState | None = None
        self._lock = threading.RLock()

        # Register callback for hot-reload
        def _on_config_change(state: ConfigState) -> None:
            """Called by ConfigSource when config changes (from its watcher thread)."""
            with self._lock:
                old_state = self._state
                self._state = state
                if old_state is None:
                    self._logger.info(
                        "ApiModelConfig[%s] loaded initial config: %d models across %d types",
                        source.name,
                        len(state.models_configs),
                        len(state.active_models),
                    )
                else:
                    # Log actual changes in active_models (not just any diff)
                    old_active = old_state.active_models
                    new_active = state.active_models
                    added_types = set(new_active.keys()) - set(old_active.keys())
                    removed_types = set(old_active.keys()) - set(new_active.keys())
                    if added_types or removed_types:
                        self._logger.info(
                            "ApiModelConfig[%s] config change detected: types added=%s removed=%s",
                            source.name, list(added_types) if added_types else [],
                            list(removed_types) if removed_types else [],
                        )

        self._source.on_config_change(_on_config_change)

    @property
    def active_models(self) -> Dict[str, List[str]]:
        """Mapping of model type to list of active model names (live from current state)."""
        with self._lock:
            if self._state is None:
                raise RuntimeError("Config not yet loaded")
            return self._state.active_models

    @property
    def models_configs(self) -> Dict[str, Dict]:
        """Full configuration dictionaries for each active model (live from current state)."""
        with self._lock:
            if self._state is None:
                raise RuntimeError("Config not yet loaded")
            return self._state.models_configs

    @property
    def source(self) -> ConfigSourceI:
        """The underlying config source."""
        return self._source

    @property
    def state(self) -> ConfigState | None:
        """Access the raw ConfigState for external consumers (read-only)."""
        with self._lock:
            return self._state

    # ------------------------------------------------------------------ #
    # Write support -- delegates to source if writable
    # ------------------------------------------------------------------ #

    def put_model_provider(
        self, model_type: str, model_name: str, provider: Dict[str, Any]
    ) -> bool:
        """
        Add a provider to an existing or new model configuration.

        Writes the entire config back through the source's put_config method.
        Thread-safe because ApiModelConfig._lock is held during read-modify-write.
        """
        with self._lock:
            if self._state is None:
                raise RuntimeError("Config not yet loaded")
            # Build a mutable copy of the full config
            full_config: Dict[str, Any] = {}
            for m_type, names in self._state.active_models.items():
                full_config[m_type] = {n: self._state.models_configs[n] for n in names}

        if not self._source.can_write:
            raise NotImplementedError(
                f"Config source '{self._source.name}' does not support writing."
            )

        # Add/update provider (threading outside lock to avoid holding it during I/O)
        with self._lock:
            if model_type not in full_config:
                full_config[model_type] = {}
            if model_name not in full_config[model_type]:
                full_config[model_type][model_name] = {"providers": []}
            existing_providers = full_config[model_type][model_name].get("providers", [])
            # Avoid duplicate providers by id
            new_id = provider.get("id")
            for p in existing_providers:
                if p.get("id") == new_id:
                    return False  # Already exists
            existing_providers.append(provider)

        success = self._source.put_config(full_config)
        if success:
            self._logger.info(
                "[ApiModelConfig] Provider %s added to model %s via etcd", provider, model_name
            )
        return success

    def remove_model_provider(
        self, model_type: str, model_name: str, provider_id: str
    ) -> bool:
        """Remove a specific provider by ID from a model. Thread-safe."""
        with self._lock:
            if self._state is None:
                raise RuntimeError("Config not yet loaded")
            full_config: Dict[str, Any] = {}
            for m_type, names in self._state.active_models.items():
                full_config[m_type] = {n: self._state.models_configs[n] for n in names}

        if model_type not in full_config or model_name not in full_config.get(model_type, {}):
            return False

        providers = full_config[model_type][model_name].get("providers", [])
        before = len(providers)
        full_config[model_type][model_name]["providers"] = [
            p for p in providers if p.get("id") != provider_id
        ]
        after = len(full_config[model_type][model_name]["providers"])

        if after == before:
            return False  # Nothing removed

        success = self._source.put_config(full_config)
        if success:
            self._logger.info(
                "[ApiModelConfig] Provider %s removed from model %s via etcd", provider_id, model_name
            )
        return success
