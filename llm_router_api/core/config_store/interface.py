"""
Abstract base class for configuration sources.

Every concrete source (file-based, etcd) implements this interface so that
``ApiModelConfig`` can read from any backend transparently.

Modeled after the existing ``KeyStoreInterface`` used for auth keys.
"""

from __future__ import annotations

import abc
from typing import Any, Callable, Dict


class ConfigState:
    """
    Immutable snapshot of a parsed models-config JSON.

    Once published, this object is treated as immutable and may be read
    by multiple threads concurrently without synchronization.
    """

    __slots__ = ("_active_models", "_models_configs")

    def __init__(self, active_models: Dict[str, list], models_configs: Dict[str, Dict]):
        self._active_models = active_models  # type: ignore[type-arg]
        self._models_configs = models_configs  # type: ignore[type-arg]

    @property
    def active_models(self) -> Dict[str, list]:
        """Mapping of model type to a list of active model names."""
        return self._active_models

    @property
    def models_configs(self) -> Dict[str, Dict]:
        """Full configuration dictionaries for each active model."""
        return self._models_configs


class ConfigSourceI(metaclass=abc.ABCMeta):
    """
    Interface that all configuration sources must implement.

    The source is the single point of truth for model configurations -- it
    loads config from its backend and exposes it as a ConfigState snapshot.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable name of this source (e.g., 'file', 'etcd')."""

    @property
    @abc.abstractmethod
    def can_write(self) -> bool:
        """Whether this source supports writing config back."""

    @abc.abstractmethod
    def get_config_state(self) -> ConfigState:
        """
        Load and parse the latest configuration from the backend.

        Returns a new immutable ``ConfigState`` snapshot. Callers should
        swap their reference to this state atomically to observe updates.

        Raises
        ------
        RuntimeError
            If the config cannot be loaded (e.g., file missing, etcd unreachable).
        """

    @abc.abstractmethod
    def on_config_change(self, callback: Callable[[ConfigState], None]) -> None:
        """
        Register a callback that fires whenever the config changes in the backend.

        Called from ``ApiModelConfig.__init__`` to announce "I am listening".
        Implementations should invoke the callback once with the initial state.

        Parameters
        ----------
        callback : Callable[[ConfigState], None]
            The function to call on every config change. Must be thread-safe
            or called from a dedicated watcher thread.
        """

    @abc.abstractmethod
    def put_config(self, config: Dict[str, Any]) -> bool:
        """
        Write the entire models config back to the backend.

        Parameters
        ----------
        config : Dict[str, Any]
            Full config dict (same schema as the JSON file).

        Returns
        -------
        bool
            True if written successfully, False otherwise.

        Raises
        ------
        NotImplementedError
            If this source does not support writing.
        """

    def close(self) -> None:
        """
        Clean up any background resources (watchers, connections).

        Called during application shutdown. Default is a no-op; override
        in sources that need cleanup.
        """
