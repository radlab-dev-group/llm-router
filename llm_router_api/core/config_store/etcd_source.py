"""
Etcd-based configuration source with hot-reload via etcd watch API.

On construction, connects to etcd and starts a background watcher thread.
When the config value changes on the etcd key, all registered callbacks
are invoked (in the watcher thread) with the new ConfigState.

Usage:
    source = EtcdConfigSource(
        host="127.0.0.1", port=2379,
        key="/llm-router/models-config"
    )
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict

try:
    import etcd3  # type: ignore[import-untyped]
except ImportError:
    etcd3 = None  # type: ignore[attr-defined]

from .interface import ConfigSourceI, ConfigState


logger = logging.getLogger(__name__)


class EtcdConfigSource(ConfigSourceI):
    """
    Loads and watches models config from an etcd key.

    Parameters
    ----------
    host : str
        Etcd server hostname or IP.
    port : int
        Etcd server TCP port (typically 2379).
    key : str
        The etcd key whose value holds the models-config JSON.
    ca_cert, cert, key_priv : str, optional
        TLS certificate paths for mTLS authentication.
    watch_initial_delay_s : float
        Grace period before starting the watch (to let initial writes settle).
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2379,
        key: str = "/llm-router/models-config",
        ca_cert: str | None = None,
        cert: str | None = None,
        key_priv: str | None = None,
        watch_initial_delay_s: float = 1.0,
    ) -> None:
        if etcd3 is None:
            raise ImportError(
                "etcd3 package is required for EtcdConfigSource. "
                "Install it with: pip install llm-router[etcd]"
            )

        self._host = host
        self._port = port
        self._key_bytes = key.encode("utf-8")
        self._ca_cert = ca_cert
        self._cert = cert
        self._key_priv = key_priv

        # Callbacks registered by ApiModelConfig instances
        self._callbacks: list[Callable[[ConfigState], None]] = []
        self._callbacks_lock = threading.Lock()

        # Current best-known state
        self._current_state: ConfigState | None = None
        self._state_lock = threading.RLock()

        # Watcher thread control
        self._watch_stop_event = threading.Event()
        self._etcd_client: etcd3.Etcd3Client | None = None
        self._watch_thread: threading.Thread | None = None

        self._connect_and_get_initial()
        time.sleep(watch_initial_delay_s)
        self._start_watcher()

    # ------------------------------------------------------------------ #
    # Interface properties
    # ------------------------------------------------------------------ #

    @property
    def name(self) -> str:
        return "etcd"

    @property
    def can_write(self) -> bool:
        return True

    # ------------------------------------------------------------------ #
    # ConfigState accessors
    # ------------------------------------------------------------------ #

    def _parse_value(self, raw_bytes: bytes | None) -> ConfigState:
        """Parse etcd value into a ConfigState (same logic as file_source)."""
        if not raw_bytes:
            raise RuntimeError("Config key exists but has no value in etcd")
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(
                f"Invalid JSON in etcd config at {self._key_bytes.decode('utf-8')}"
            ) from exc

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

        models_configs: Dict[str, Dict] = {}
        for m_type, models_list in active_models.items():
            for m_name in models_list:
                model_config = data[m_type][m_name]
                if "providers" not in model_config:
                    raise KeyError(f"{m_type}:{m_name} has no providers!")
                models_configs[m_name] = model_config

        return ConfigState(active_models, models_configs)

    def get_config_state(self) -> ConfigState:
        """Return the latest known-good ConfigState. If etcd is disconnected, returns last known."""
        with self._state_lock:
            if self._current_state is not None:
                return self._current_state
        raise RuntimeError(
            "Etcd config source has no valid state -- connection may be down"
        )

    # ------------------------------------------------------------------ #
    # Callback registration (called by ApiModelConfig)
    # ------------------------------------------------------------------ #

    def on_config_change(self, callback: Callable[[ConfigState], None]) -> None:
        with self._callbacks_lock:
            self._callbacks.append(callback)
        # Fire once with the initial state so the caller gets current data immediately
        with self._state_lock:
            state = self._current_state
        if state is not None:
            callback(state)

    def _notify_callbacks(self, state: ConfigState) -> None:
        """Invoke all registered callbacks with the new state. Safe to call from watcher thread."""
        with self._callbacks_lock:
            for cb in list(self._callbacks):
                try:
                    cb(state)
                except Exception:  # pylint: disable=broad-exception-caught
                    logger.exception("Error in config change callback")

    # ------------------------------------------------------------------ #
    # Writing (put_config) -- used for runtime provider management
    # ------------------------------------------------------------------ #

    def put_config(self, config: Dict[str, Any]) -> bool:
        """Write the entire config dict to etcd as JSON."""
        if self._etcd_client is None:
            return False
        try:
            self._etcd_client.put(
                self._key_bytes.decode("utf-8"),
                json.dumps(config, indent=2),
            )
            # After writing, update local state directly (the watcher will pick it up)
            state = self._parse_value(json.dumps(config).encode())
            with self._state_lock:
                self._current_state = state
            return True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error("Failed to write config to etcd: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #

    def _connect_etcd(self) -> "etcd3.Etcd3Client":
        """Create an etcd3 client, optionally with TLS."""
        kwargs: dict = {
            "host": self._host,
            "port": self._port,
        }
        if self._ca_cert:
            kwargs["ca_cert"] = self._ca_cert  # type: ignore[arg-type]
        if self._cert:
            kwargs["cert"] = (self._cert, self._key_priv)  # type: ignore[arg-type]

        client = etcd3.Etcd3Client(**kwargs)  # type: ignore[attr-defined]

        # Verify connectivity immediately (etcd3 is lazy by default)
        try:
            client.status()
        except Exception as exc:
            raise ConnectionError(
                f"Etcd unreachable at {self._host}:{self._port}: {exc}"
            ) from exc
        return client

    def _connect_and_get_initial(self) -> None:
        """Connect to etcd and read the initial config value."""
        # Exponential backoff retry for startup connection
        retries = 5
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                self._etcd_client = self._connect_etcd()
                value, _metadata = self._etcd_client.get(self._key_bytes)  # type: ignore[attr-defined]
                state = self._parse_value(value)
                with self._state_lock:
                    self._current_state = state
                logger.info(
                    "[ConfigSource] Connected to etcd at %s:%d, key=%s",
                    self._host, self._port, self._key_bytes.decode("utf-8"),
                )
                return
            except Exception as exc:  # pylint: disable=broad-exception-caught
                last_exc = exc
                logger.warning(
                    "[ConfigSource] Etcd connection attempt %d/%d failed: %s",
                    attempt + 1, retries, exc,
                )
                time.sleep(delay)
                delay *= 2

        raise ConnectionError(
            f"Could not connect to etcd at {self._host}:{self._port} "
            f"after {retries} attempts: {last_exc}"
        )

    # ------------------------------------------------------------------ #
    # Watcher thread
    # ------------------------------------------------------------------ #

    def _start_watcher(self) -> None:
        """Start the background watcher thread."""
        self._watch_thread = threading.Thread(
            target=self._watch_loop, daemon=True, name="config-etcd-watch"
        )
        self._watch_thread.start()
        logger.info("[ConfigSource] Etcd watch thread started for key=%s",
                    self._key_bytes.decode("utf-8"))

    def _watch_loop(self) -> None:
        """
        Main watcher loop with auto-reconnect on disconnection.
        Uses etcd's long-poll watch API (no polling).
        """
        backoff_delay = 1.0
        max_backoff = 30.0

        while not self._watch_stop_event.is_set():
            if self._etcd_client is None:
                logger.warning("[ConfigSource] etcd client lost; attempting reconnect...")
                time.sleep(backoff_delay)
                try:
                    self._etcd_client = self._connect_etcd()
                    backoff_delay = 1.0  # reset on success
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.warning("[ConfigSource] Reconnect failed: %s", exc)
                    backoff_delay = min(backoff_delay * 2, max_backoff)
                    continue

            try:
                # Use etcd's watch_prefix (blocking long-poll) -- NOT polling
                events = self._etcd_client.watch_prefix(self._key_bytes.decode("utf-8"))  # type: ignore[attr-defined]
                for event in events:
                    if self._watch_stop_event.is_set():
                        break

                    new_value = None
                    if hasattr(event, 'event') and hasattr(event.event, 'value'):
                        new_value = event.event.value
                    elif hasattr(event, 'value'):
                        new_value = event.value
                    else:
                        continue  # skip delete events for now

                    try:
                        state = self._parse_value(new_value)
                        with self._state_lock:
                            old = self._current_state
                            self._current_state = state
                        if old is None or old.active_models != state.active_models:
                            logger.info("[ConfigSource] Config updated from etcd, notifying %d listeners", len(self._callbacks))
                            self._notify_callbacks(state)
                        backoff_delay = 1.0  # reset on successful watch
                    except RuntimeError as exc:
                        logger.error("[ConfigSource] Failed to parse config from etcd: %s", exc)

            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "[ConfigSource] Watch lost (%s); reconnecting in %.1fs",
                    type(exc).__name__, backoff_delay,
                )
                backoff_delay = min(backoff_delay * 2, max_backoff)
                self._etcd_client = None  # force reconnect in outer loop

    def close(self) -> None:
        """Stop the watcher thread."""
        self._watch_stop_event.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=5.0)
        if self._etcd_client is not None:
            try:
                self._etcd_client.close()  # type: ignore[attr-defined]
            except Exception:  # pylint: disable=broad-exception-caught
                pass
