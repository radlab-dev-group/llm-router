"""
File-based configuration source -- the current behavior, wrapped as ConfigSourceI.

Config is read from a local JSON file on every ``get_config_state()`` call.
No hot-reload: callbacks registered via ``on_config_change`` are invoked
once at init with the current state and then never again.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict

from .interface import ConfigSourceI, ConfigState


logger = logging.getLogger(__name__)


class FileConfigSource(ConfigSourceI):
    """
    Loads models config from a local JSON file.

    This is functionally identical to the original behavior -- config is read
    on every get_config_state() call, but there is NO hot-reload (no watcher).
    Callbacks registered via on_config_change are invoked once at init with the
    current state.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise FileNotFoundError(f"Config file not found: {self._path}")
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[ConfigState], None]] = []

    @property
    def name(self) -> str:
        return "file"

    @property
    def can_write(self) -> bool:
        return False

    def _parse_file(self) -> ConfigState:
        with self._lock:
            raw = self._path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Invalid JSON in config file {self._path}"
            ) from exc

        # Replicate the original _read_active_models logic
        active_models: Dict[str, list] = {}
        if data:
            exists_model = False
            for _mtype, model_list in data.items():
                if model_list:
                    exists_model = True
                    break
            if not exists_model:
                active_models = {}
            else:
                active_models = data["active_models"]

        # Replicate the original _active_models_configuration logic
        models_configs: Dict[str, Dict] = {}
        for m_type, models_list in active_models.items():
            for m_name in models_list:
                model_config = data[m_type][m_name]
                if "providers" not in model_config:
                    raise KeyError(f"{m_type}:{m_name} has no providers!")
                models_configs[m_name] = model_config

        return ConfigState(active_models, models_configs)

    def get_config_state(self) -> ConfigState:
        return self._parse_file()

    def on_config_change(self, callback: Callable[[ConfigState], None]) -> None:
        self._callbacks.append(callback)
        # Fire once with initial state -- this is the current config
        state = self._parse_file()
        callback(state)

    def put_config(self, config: Dict[str, Any]) -> bool:
        raise NotImplementedError(
            "FileConfigSource does not support writing. "
            "Use an etcd-backed source for runtime config updates."
        )

    def close(self) -> None:
        self._callbacks.clear()
