"""Tests for the config_store package (FileConfigSource, EtcdConfigSource, factory)."""

from __future__ import annotations

import json
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest


class TestFileConfigSource:
    """FileConfigSource behaviour."""

    def test_name(self):
        from llm_router_api.core.config_store.file_source import FileConfigSource

        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump({"active_models": {}, "openai": {}}, f)
            path = f.name

        source = FileConfigSource(path=path)
        assert source.name == "file"

    def test_can_write_is_false(self):
        from llm_router_api.core.config_store.file_source import FileConfigSource

        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump({"active_models": {}, "openai": {}}, f)
            path = f.name

        source = FileConfigSource(path=path)
        assert source.can_write is False

    def test_get_config_state_returns_valid_state(self):
        from llm_router_api.core.config_store.file_source import FileConfigSource
        from llm_router_api.core.config_store.interface import ConfigState

        config_data = {
            "active_models": {"openai": ["gpt-4"]},
            "openai": {
                "gpt-4": {
                    "api_host": "https://openai.example.com",
                    "providers": [{"id": "p1"}],
                }
            },
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump(config_data, f)
            path = f.name

        source = FileConfigSource(path=path)
        state = source.get_config_state()

        assert isinstance(state, ConfigState)
        assert "gpt-4" in state.active_models["openai"]
        assert "p1" == state.models_configs["gpt-4"]["providers"][0]["id"]

    def test_put_config_raises(self):
        from llm_router_api.core.config_store.file_source import FileConfigSource

        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump({"active_models": {}, "openai": {}}, f)
            path = f.name

        source = FileConfigSource(path=path)
        with pytest.raises(NotImplementedError, match="does not support writing"):
            source.put_config({})

    def test_on_config_change_fires_once_with_initial(self):
        from llm_router_api.core.config_store.file_source import FileConfigSource

        config_data = {
            "active_models": {"openai": ["gpt-4"]},
            "openai": {
                "gpt-4": {
                    "api_host": "https://openai.example.com",
                    "providers": [{"id": "p1"}],
                }
            },
        }
        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump(config_data, f)
            path = f.name

        source = FileConfigSource(path=path)
        fired = []

        def cb(state):
            fired.append(state)

        source.on_config_change(cb)
        assert len(fired) == 1
        assert "gpt-4" in fired[0].models_configs


class TestEtcdConfigSource:
    """EtcdConfigSource behaviour (mocked etcd3 client)."""

    @pytest.fixture
    def mock_etcd_client(self):
        """Return a mock etcd3.Etcd3Client."""
        mock_client = MagicMock()
        mock_client.status.return_value = MagicMock()
        mock_client.get.return_value = (
            json.dumps(
                {
                    "active_models": {"openai": ["gpt-4"]},
                    "openai": {
                        "gpt-4": {
                            "api_host": "https://openai.example.com",
                            "providers": [{"id": "p1"}],
                        }
                    },
                }
            ).encode(),
            None,
        )
        return mock_client

    @pytest.fixture
    def source(self, mock_etcd_client):
        """Create an EtcdConfigSource with a mocked etcd3 client."""
        import etcd3  # ensure import works
        from llm_router_api.core.config_store.etcd_source import EtcdConfigSource

        with patch("etcd3.Etcd3Client", return_value=mock_etcd_client):
            src = EtcdConfigSource(host="127.0.0.1", port=2379, key="/test/config")
            yield src
            src.close()

    def test_name(self, source):
        assert source.name == "etcd"

    def test_can_write_is_true(self, source):
        assert source.can_write is True

    def test_get_config_state_returns_valid_state(self, source):
        from llm_router_api.core.config_store.interface import ConfigState

        state = source.get_config_state()
        assert isinstance(state, ConfigState)
        assert "gpt-4" in state.active_models["openai"]

    def test_put_config_calls_etcd_put(self, source, mock_etcd_client):
        new_config = {
            "active_models": {"openai": ["gpt-4", "gpt-3.5"]},
            "openai": {
                "gpt-4": {
                    "api_host": "https://openai.example.com",
                    "providers": [{"id": "p1"}],
                },
                "gpt-3.5": {
                    "api_host": "https://openai.example.com",
                    "providers": [{"id": "p2"}],
                },
            },
        }
        result = source.put_config(new_config)
        assert result is True
        mock_etcd_client.put.assert_called_once()

    def test_put_config_returns_false_when_disconnected(self, source):
        source._etcd_client = None  # simulate disconnect
        assert source.put_config({}) is False


class TestFactory:
    """create_config_source factory function."""

    def test_create_file_source(self):
        from llm_router_api.core.config_store import create_config_source

        with tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False
        ) as f:
            json.dump({"active_models": {}, "openai": {}}, f)
            path = f.name

        source = create_config_source("file", path=path)
        assert source.name == "file"

    def test_create_unknown_type_raises(self):
        from llm_router_api.core.config_store import create_config_source

        with pytest.raises(ValueError, match="Unknown config source type"):
            create_config_source("unknown")


class TestConfigState:
    """Immutability and basic properties of ConfigState."""

    def test_active_models_and_models_configs(self):
        from llm_router_api.core.config_store.interface import ConfigState

        state = ConfigState({"openai": ["gpt-4"]}, {"gpt-4": {}})
        assert state.active_models == {"openai": ["gpt-4"]}
        assert state.models_configs == {"gpt-4": {}}

    def test_cannot_add_new_attributes(self):
        from llm_router_api.core.config_store.interface import ConfigState

        state = ConfigState({"openai": ["gpt-4"]}, {})
        with pytest.raises(AttributeError):
            state.new_attr = "foo"


class TestHotReloadIntegration:
    """End-to-end test: config change propagates to ApiModelConfig listeners."""

    def test_callback_propagates_config_change(self):
        """When config source fires a callback, ApiModelConfig updates its state."""
        from llm_router_api.core.config_store.interface import ConfigSourceI, ConfigState
        from llm_router_api.core.model_config import ApiModelConfig

        # Minimal mock source that supports hot-reload callbacks
        class MockHotReloadSource(ConfigSourceI):
            def __init__(self):
                self._callbacks = []
                self._state = ConfigState(
                    {"openai": ["gpt-4"]},
                    {"gpt-4": {"providers": [{"id": "p1"}]}},
                )

            @property
            def name(self):
                return "mock"

            @property
            def can_write(self):
                return True

            def get_config_state(self):
                return self._state

            def on_config_change(self, callback):
                self._callbacks.append(callback)
                # Fire once with initial state (as real sources do)
                callback(self._state)

            def put_config(self, config):
                new_state = ConfigState(
                    {"openai": ["gpt-4", "gpt-3.5"]},
                    {
                        "gpt-4": {"providers": [{"id": "p1"}]},
                        "gpt-3.5": {"providers": [{"id": "p2"}]},
                    },
                )
                self._state = new_state
                for cb in list(self._callbacks):
                    cb(new_state)
                return True

            def close(self):
                pass

        source = MockHotReloadSource()

        # Create ApiModelConfig — should register callback and load initial config
        api_config = ApiModelConfig(source=source)
        assert "gpt-4" in api_config.active_models["openai"]

        # Simulate a config change via put_config (which triggers callbacks)
        success = source.put_config({})
        assert success is True

        # ApiModelConfig should now see the updated state
        assert "gpt-3.5" in api_config.active_models["openai"]
