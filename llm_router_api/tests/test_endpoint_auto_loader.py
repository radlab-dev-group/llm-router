"""
Unit tests for :class:`llm_router_api.register.auto_loader.EndpointAutoLoader`.

Covers, without touching the network or real services:

* constructor wiring – base class, prompt handler, model handler and the
  provider‑chooser delegation;
* :meth:`discover_classes_in_package` – subclass discovery inside a package
  and the module‑prefix / base‑class filters;
* :meth:`instantiate_with_defaults` – kwargs forwarding, skipping of the
  special‑case endpoint classes and of constructors that require arguments;
* :meth:`instantiate_from_config` – the custom resolver path, the
  importlib‑based resolution, args/kwargs defaults and the subclass
  type‑check.
"""

from __future__ import annotations

import json
import os
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from rdl_ml_utils.handlers.prompt_handler import PromptHandler  # noqa: E402

from llm_router_api.core.model_handler import ModelHandler  # noqa: E402
from llm_router_api.endpoints.builtin.builtin_utils import (  # noqa: E402
    TextListUtilityEndpoint,
)
from llm_router_api.endpoints.builtin.openai import (  # noqa: E402
    OpenAIResponseHandler,
)
from llm_router_api.endpoints.endpoint_i import (  # noqa: E402
    EndpointI,
    EndpointWithHttpRequestI,
)
from llm_router_api.endpoints.passthrough import PassthroughI  # noqa: E402
from llm_router_api.register.auto_loader import EndpointAutoLoader  # noqa: E402


def _write_models_config(tmp_path) -> str:
    path = tmp_path / "models-config.json"
    path.write_text(
        json.dumps(
            {
                "active_models": {"openai": ["m1"]},
                "openai": {"m1": {"providers": [{"id": "p1"}]}},
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture()
def chooser() -> mock.Mock:
    return mock.Mock(name="ProviderStrategyFacade")


@pytest.fixture()
def loader(tmp_path, chooser) -> EndpointAutoLoader:
    return EndpointAutoLoader(
        base_class=EndpointI,
        prompts_dir=str(tmp_path),
        models_config_path=_write_models_config(tmp_path),
        provider_chooser=chooser,
    )


class _CapturingEndpoint(EndpointI):
    """Concrete endpoint that records its constructor arguments."""

    def __init__(self, *args, **kwargs):
        super().__init__(ep_name="captured_ep", api_types=["builtin"])
        self.constructor_args = args
        self.constructor_kwargs = kwargs

    def prepare_payload(self, params):
        return params


class _BrokenConstructorEndpoint(EndpointI):
    """Endpoint whose constructor requires a positional argument."""

    def __init__(self, required_argument):
        super().__init__(ep_name="broken_ep", api_types=["builtin"])

    def prepare_payload(self, params):
        return params


class _NotAnEndpoint:
    """Plain class used to exercise the subclass type‑check."""


class _ForeignBase:
    """Unrelated base class for the discovery filter tests."""


class _ForeignEndpoint(_ForeignBase):
    """Subclass of ``_ForeignBase`` living in *this* test module."""


class TestConstructor:
    def test_stores_base_class_and_prompts_dir(self, loader, tmp_path):
        assert loader.base_class is EndpointI
        assert loader.prompts_dir == str(tmp_path)

    def test_creates_prompt_handler_bound_to_prompts_dir(self, loader, tmp_path):
        assert isinstance(loader._prompt_handler, PromptHandler)
        assert loader._prompt_handler.base_dir == tmp_path

    def test_creates_model_handler_with_config(self, loader):
        assert isinstance(loader._model_handler, ModelHandler)
        assert loader._model_handler.api_model_config.active_models == {
            "openai": ["m1"]
        }

    def test_provider_chooser_delegated_to_model_handler(self, loader, chooser):
        assert loader._model_handler.provider_chooser is chooser


class TestDiscoverClassesInPackage:
    def test_returns_list_of_endpoint_subclasses(self, loader):
        discovered = loader.discover_classes_in_package("llm_router_api.endpoints")
        assert isinstance(discovered, list)
        assert discovered
        for cls in discovered:
            assert isinstance(cls, type)
            assert issubclass(cls, EndpointI)

    def test_known_endpoints_are_discovered(self, loader):
        discovered = set(
            loader.discover_classes_in_package("llm_router_api.endpoints")
        )
        for expected in (
            PassthroughI,
            EndpointWithHttpRequestI,
            OpenAIResponseHandler,
            TextListUtilityEndpoint,
        ):
            assert expected in discovered

    def test_classes_outside_package_are_filtered_out(self, loader):
        discovered = set(
            loader.discover_classes_in_package("llm_router_api.endpoints")
        )
        # These helpers live in the test module, i.e. outside the scanned
        # package, so the module‑prefix filter must drop them.
        assert _CapturingEndpoint not in discovered
        assert _BrokenConstructorEndpoint not in discovered
        assert _ForeignEndpoint not in discovered

    def test_discovery_respects_the_configured_base_class(self, tmp_path):
        loader = EndpointAutoLoader(
            base_class=_ForeignBase,
            prompts_dir=str(tmp_path),
            models_config_path=_write_models_config(tmp_path),
            provider_chooser=mock.Mock(),
        )
        discovered = loader.discover_classes_in_package("llm_router_api.endpoints")
        # No endpoint is a subclass of the foreign base class.
        assert discovered == []


class TestInstantiateWithDefaults:
    def test_forwards_standard_kwargs(self, loader):
        instances = loader.instantiate_with_defaults([_CapturingEndpoint])
        assert len(instances) == 1
        instance = instances[0]
        assert isinstance(instance, _CapturingEndpoint)
        assert instance.constructor_kwargs["model_handler"] is loader._model_handler
        assert (
            instance.constructor_kwargs["prompt_handler"] is loader._prompt_handler
        )

    def test_special_case_classes_are_skipped(self, loader):
        special = [
            PassthroughI,
            EndpointWithHttpRequestI,
            TextListUtilityEndpoint,
            OpenAIResponseHandler,
        ]
        assert loader.instantiate_with_defaults(special) == []

    def test_broken_constructor_is_skipped(self, loader):
        instances = loader.instantiate_with_defaults(
            [_CapturingEndpoint, _BrokenConstructorEndpoint]
        )
        assert [type(item) for item in instances] == [_CapturingEndpoint]

    def test_broken_constructor_is_logged(self, loader):
        loader._logger = mock.Mock()
        loader.instantiate_with_defaults([_BrokenConstructorEndpoint])
        loader._logger.warning.assert_called()

    def test_empty_input_yields_empty_output(self, loader):
        assert loader.instantiate_with_defaults([]) == []


class TestInstantiateFromConfig:
    def test_resolver_with_args_and_kwargs(self, loader):
        instances = loader.instantiate_from_config(
            [
                {"class": "my_ep", "args": [1, 2], "kwargs": {"opt": "v"}},
                {"class": "my_ep"},
            ],
            class_resolver=lambda name: _CapturingEndpoint,
        )
        assert len(instances) == 2
        assert instances[0].constructor_args == (1, 2)
        assert instances[0].constructor_kwargs == {"opt": "v"}
        assert instances[1].constructor_args == ()
        assert instances[1].constructor_kwargs == {}

    def test_resolver_called_for_every_entry(self, loader):
        resolver = mock.Mock(return_value=_CapturingEndpoint)
        loader.instantiate_from_config(
            [{"class": "a"}, {"class": "b"}], class_resolver=resolver
        )
        assert resolver.call_count == 2
        assert [call.args for call in resolver.call_args_list] == [
            ("a",),
            ("b",),
        ]

    def test_importlib_resolution_via_module_path(self, loader):
        instances = loader.instantiate_from_config(
            [
                {
                    "class": (
                        "llm_router_api.endpoints.builtin.openai."
                        "OpenAIModelsHandler"
                    )
                }
            ]
        )
        assert len(instances) == 1
        assert type(instances[0]).__name__ == "OpenAIModelsHandler"

    def test_non_endpoint_class_rejected(self, loader):
        with pytest.raises(TypeError, match="not a subclass"):
            loader.instantiate_from_config(
                [{"class": "x"}], class_resolver=lambda name: _NotAnEndpoint
            )

    def test_unknown_class_via_importlib_raises_attribute_error(self, loader):
        with pytest.raises(AttributeError):
            loader.instantiate_from_config(
                [
                    {
                        "class": (
                            "llm_router_api.endpoints.builtin.builtin_utils."
                            "DoesNotExist"
                        )
                    }
                ]
            )
