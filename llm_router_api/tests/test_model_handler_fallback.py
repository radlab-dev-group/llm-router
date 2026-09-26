"""
Unit tests for the ``fallback_model`` chain in ``ModelHandler``.

``ModelHandler.get_model_provider`` resolves the model that actually serves a
request *before* load balancing: when the requested model has no providers,
has no healthy provider, or keeps every provider busy until the strategy
timeout, the next model of the ``model -> fallback_model -> ...`` chain is
handed to the load-balancing strategy instead.

The provider chooser is a mock; config files are written to ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.model_handler import ModelHandler  # noqa: E402

LOGGER_NAME = "llm_router_api.core.model_handler"


def _provider(pid: str, input_size: int = 1000) -> dict:
    return {
        "id": pid,
        "api_host": f"http://{pid}",
        "api_type": "vllm",
        "input_size": input_size,
    }


def _payload() -> dict:
    return {
        "active_models": {"models": ["a", "b", "c", "solo", "empty", "empty_leaf"]},
        "models": {
            "a": {"providers": [_provider("pa")], "fallback_model": "b"},
            "b": {"providers": [_provider("pb")], "fallback_model": "c"},
            # "c" deliberately has a smaller context than "a"/"b".
            "c": {"providers": [_provider("pc", input_size=64)]},
            "solo": {"providers": [_provider("ps")]},
            "empty": {"providers": [], "fallback_model": "b"},
            "empty_leaf": {"providers": []},
        },
    }


def _chooser_returning(results: dict):
    """
    Build a ``get_provider`` side effect from a model-name to outcome map.

    Values may be a provider dictionary or an exception to raise; models that
    are absent from the map are served by their first configured provider.
    """

    def _choose(model_name, providers, options=None):
        outcome = results.get(model_name, providers[0])
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return _choose


def _models_consulted(chooser) -> list:
    return [c.kwargs["model_name"] for c in chooser.get_provider.call_args_list]


@pytest.fixture(name="chooser")
def fixture_chooser():
    chooser = mock.Mock()
    # "availability unknown" is the safe default: the handler must then use
    # the regular blocking selection path.
    chooser.has_available_provider.return_value = None
    chooser.get_provider.side_effect = _chooser_returning({})
    return chooser


@pytest.fixture(name="handler")
def fixture_handler(tmp_path, chooser):
    path = tmp_path / "models-config.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    return ModelHandler(str(path), chooser)


class TestNoFallbackNeeded:
    def test_primary_model_serves(self, handler, chooser):
        model = handler.get_model_provider("a")
        assert model.id == "pa"
        assert model.name == "a"
        assert _models_consulted(chooser) == ["a"]
        chooser.record_model_fallback.assert_not_called()

    def test_probe_is_consulted_only_for_non_final_hops(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {"a": TimeoutError("busy"), "b": TimeoutError("busy")}
        )
        handler.get_model_provider("a")
        probed = [
            c.kwargs["model_name"]
            for c in chooser.has_available_provider.call_args_list
        ]
        # "c" is the last hop and must keep the full blocking behaviour.
        assert probed == ["a", "b"]

    def test_model_without_fallback_is_served_normally(self, handler, chooser):
        model = handler.get_model_provider("solo")
        assert model.id == "ps"
        assert _models_consulted(chooser) == ["solo"]

    def test_model_without_fallback_still_raises_on_timeout(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {"solo": TimeoutError("no provider")}
        )
        with pytest.raises(TimeoutError):
            handler.get_model_provider("solo")
        assert _models_consulted(chooser) == ["solo"]


class TestFallbackOnSelectionTimeout:
    def test_single_hop_fallback(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {"a": TimeoutError("no provider")}
        )
        model = handler.get_model_provider("a")
        assert model.id == "pb"
        assert _models_consulted(chooser) == ["a", "b"]

    def test_chain_walks_to_the_last_model(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {"a": TimeoutError("busy"), "b": TimeoutError("busy")}
        )
        model = handler.get_model_provider("a")
        assert model.id == "pc"
        assert _models_consulted(chooser) == ["a", "b", "c"]

    def test_timeout_of_the_last_hop_propagates(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {
                "a": TimeoutError("busy"),
                "b": TimeoutError("busy"),
                "c": TimeoutError("busy"),
            }
        )
        with pytest.raises(TimeoutError):
            handler.get_model_provider("a")
        assert _models_consulted(chooser) == ["a", "b", "c"]

    def test_strategy_returning_none_moves_to_fallback(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning({"a": None})
        model = handler.get_model_provider("a")
        assert model.id == "pb"

    def test_last_hop_returning_none_yields_none(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {"a": TimeoutError("busy"), "b": TimeoutError("busy"), "c": None}
        )
        assert handler.get_model_provider("a") is None


class TestFastFailOnUnhealthyProviders:
    def test_unhealthy_primary_is_skipped_without_waiting(self, handler, chooser):
        chooser.has_available_provider.side_effect = lambda model_name, providers: (
            model_name != "a"
        )
        model = handler.get_model_provider("a")
        assert model.id == "pb"
        # The primary is never handed to the strategy.
        assert _models_consulted(chooser) == ["b"]
        chooser.has_available_provider.assert_any_call(
            model_name="a", providers=[_provider("pa")]
        )

    def test_probe_is_never_used_for_the_last_hop(self, handler, chooser):
        chooser.has_available_provider.return_value = False
        chooser.get_provider.side_effect = _chooser_returning(
            {"solo": TimeoutError("busy")}
        )
        with pytest.raises(TimeoutError):
            handler.get_model_provider("solo")
        chooser.has_available_provider.assert_not_called()

    @pytest.mark.parametrize("probe_answer", [True, None])
    def test_known_good_or_unknown_probe_keeps_primary(
        self, handler, chooser, probe_answer
    ):
        chooser.has_available_provider.return_value = probe_answer
        model = handler.get_model_provider("a")
        assert model.id == "pa"
        assert _models_consulted(chooser) == ["a"]


class TestModelWithoutProviders:
    def test_missing_providers_fall_back(self, handler, chooser):
        model = handler.get_model_provider("empty")
        assert model.id == "pb"
        assert _models_consulted(chooser) == ["b"]

    def test_missing_providers_without_fallback_returns_none(
        self, handler, chooser, caplog
    ):
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            assert handler.get_model_provider("empty_leaf") is None
        chooser.get_provider.assert_not_called()
        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "No provider available for model 'empty_leaf'" in messages
        # A single-model chain is not presented as a fallback chain.
        assert "fallback chain" not in messages

    def test_fake_mode_uses_first_hop_with_providers(self, handler, chooser):
        model = handler.get_model_provider("empty", fake=True)
        assert model.id == "pb"
        chooser.get_provider.assert_not_called()
        chooser.has_available_provider.assert_not_called()

    def test_fake_mode_keeps_primary_providers(self, handler, chooser):
        model = handler.get_model_provider("a", fake=True)
        assert model.id == "pa"


class TestFallbackBookkeeping:
    def test_provider_is_released_under_the_serving_model_key(
        self, handler, chooser
    ):
        chooser.get_provider.side_effect = _chooser_returning({"a": TimeoutError()})
        model = handler.get_model_provider("a")

        # ``EndpointI.unset_model`` derives the model name from the ApiModel,
        # which must be the model whose provider lock has to be released.
        assert model.name == "b"
        handler.put_model_provider(model.name, model.as_dict())
        chooser.put_provider.assert_called_once_with(
            model_name="b", provider=model.as_dict(), options=None
        )

    def test_fallback_is_counted_once_for_the_serving_model(self, handler, chooser):
        chooser.get_provider.side_effect = _chooser_returning(
            {"a": TimeoutError("busy"), "b": TimeoutError("busy")}
        )
        handler.get_model_provider("a")
        chooser.record_model_fallback.assert_called_once_with(
            model_name="a", fallback_model="c"
        )

    def test_handler_survives_chooser_without_metric_support(self, tmp_path):
        chooser = mock.Mock(
            spec=["get_provider", "put_provider", "has_available_provider"]
        )
        chooser.has_available_provider.return_value = None
        chooser.get_provider.side_effect = _chooser_returning({})
        path = tmp_path / "models-config.json"
        path.write_text(json.dumps(_payload()), encoding="utf-8")

        handler = ModelHandler(str(path), chooser)
        assert handler.get_model_provider("a").id == "pa"

    def test_smaller_fallback_context_is_logged(self, handler, chooser, caplog):
        chooser.get_provider.side_effect = _chooser_returning(
            {"a": TimeoutError("busy"), "b": TimeoutError("busy")}
        )
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            handler.get_model_provider("a")

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "smaller context" in messages

    def test_fallback_switch_is_logged(self, handler, chooser, caplog):
        chooser.get_provider.side_effect = _chooser_returning({"a": TimeoutError()})
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            handler.get_model_provider("a")

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "falling back to model 'b'" in messages

    def test_whole_chain_failure_is_logged(self, handler, chooser, caplog):
        chooser.get_provider.side_effect = _chooser_returning(
            {
                "a": TimeoutError("busy"),
                "b": TimeoutError("busy"),
                "c": TimeoutError("busy"),
            }
        )
        with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
            with pytest.raises(TimeoutError):
                handler.get_model_provider("a")

        messages = " ".join(record.getMessage() for record in caplog.records)
        assert "fallback chain: a -> b -> c" in messages


class TestChainConstruction:
    def test_unknown_model_still_raises_key_error(self, handler):
        with pytest.raises(KeyError):
            handler.get_model_provider("nope")

    def test_chain_stops_at_model_without_fallback(self, handler):
        assert handler._fallback_chain("a") == ["a", "b", "c"]

    def test_chain_of_model_without_fallback_is_a_single_hop(self, handler):
        assert handler._fallback_chain("solo") == ["solo"]

    def test_hand_built_cycle_does_not_loop(self, handler):
        configs = handler.api_model_config.models_configs
        configs["c"]["fallback_model"] = "a"
        assert handler._fallback_chain("a") == ["a", "b", "c"]
