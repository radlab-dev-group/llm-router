"""
Unit tests for :class:`llm_router_api.register.register.FlaskEndpointRegistrar`.

The registrar wires :class:`EndpointI` objects into a Flask application
(or blueprint).  All behaviour is exercised through a real Flask test
client — no network, no external services:

* constructor validation and URL‑prefix normalisation;
* route registration – normalisation, ``add_api_prefix`` handling,
  duplicate detection, app and blueprint modes;
* the generated view – parameter extraction (query / JSON / form),
  streaming responses, plain‑text and ``(body, status)`` results,
  ``ValueError`` → 400 and other exceptions → 500;
* the context‑manager protocol.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from flask import Blueprint, Flask  # noqa: E402

from llm_router_api.base.constants import DEFAULT_API_PREFIX  # noqa: E402
from llm_router_api.endpoints.endpoint_i import EndpointI  # noqa: E402
from llm_router_api.register.register import FlaskEndpointRegistrar  # noqa: E402


class _DummyEndpoint(EndpointI):
    """Concrete endpoint whose ``run_ep`` behaviour is injected per test."""

    def __init__(
        self,
        ep_name: str = "dummy",
        method: str = "POST",
        dont_add_api_prefix: bool = False,
        behavior: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method=method,
            dont_add_api_prefix=dont_add_api_prefix,
        )
        self._behavior = behavior

    def prepare_payload(self, params):
        return params

    def run_ep(self, params):
        if self._behavior is not None:
            return self._behavior(params)
        return {"ok": True, "params": params}


def _make_app(*endpoints) -> Flask:
    app = Flask(__name__)
    registrar = FlaskEndpointRegistrar(app=app)
    for ep in endpoints:
        registrar.register_endpoint(ep)
    return app


def _rules(app: Flask) -> set:
    return {rule.rule for rule in app.url_map.iter_rules()}


class TestConstructor:
    def test_requires_app_or_blueprint(self):
        with pytest.raises(ValueError, match="app.*blueprint"):
            FlaskEndpointRegistrar()

    def test_default_prefix_comes_from_constants(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__))
        assert registrar._prefix == DEFAULT_API_PREFIX

    def test_prefix_gets_leading_slash(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__), url_prefix="api/v1")
        assert registrar._prefix == "/api/v1"

    def test_prefix_with_leading_slash_kept(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__), url_prefix="/api/v1")
        assert registrar._prefix == "/api/v1"

    def test_empty_prefix_disables_prefixing(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__), url_prefix="")
        assert registrar._prefix == ""


class TestRegistration:
    def test_route_registered_with_global_prefix(self):
        app = _make_app(_DummyEndpoint(ep_name="dummy"))
        assert f"{DEFAULT_API_PREFIX}/dummy" in _rules(app)

    def test_lowercase_method_uppercased_in_route_name(self):
        # ``EndpointI`` itself rejects lowercase methods, so exercise the
        # registrar's ``.upper()`` with a duck‑typed endpoint object.
        class _RawEndpoint:
            name = "low"
            method = "post"
            add_api_prefix = True

            def run_ep(self, params):
                return {"ok": True}

        app = Flask(__name__)
        registrar = FlaskEndpointRegistrar(app=app)
        endpoint = _RawEndpoint()
        registrar.register_endpoint(endpoint)
        expected = f"_RawEndpoint:POST:{DEFAULT_API_PREFIX}/low"
        assert expected in app.view_functions
        assert f"{DEFAULT_API_PREFIX}/low" in _rules(app)

    def test_endpoint_name_with_leading_slash_not_doubled(self):
        app = _make_app(_DummyEndpoint(ep_name="/pre", dont_add_api_prefix=True))
        assert "/pre" in _rules(app)
        assert "//pre" not in _rules(app)

    def test_dont_add_api_prefix_skips_prefix(self):
        app = _make_app(_DummyEndpoint(ep_name="bare", dont_add_api_prefix=True))
        assert "/bare" in _rules(app)
        assert f"{DEFAULT_API_PREFIX}/bare" not in _rules(app)

    def test_duplicate_rule_and_method_rejected(self):
        app = Flask(__name__)
        registrar = FlaskEndpointRegistrar(app=app)
        registrar.register_endpoint(_DummyEndpoint(ep_name="dup"))
        with pytest.raises(RuntimeError, match="Duplicate route: POST"):
            registrar.register_endpoint(_DummyEndpoint(ep_name="dup"))

    def test_same_rule_different_methods_allowed(self):
        app = _make_app(
            _DummyEndpoint(ep_name="both", method="GET"),
            _DummyEndpoint(ep_name="both", method="POST"),
        )
        assert len(_rules(app)) == 2

    def test_register_endpoints_accepts_list_and_generator(self):
        app = _make_app(
            *[
                _DummyEndpoint(ep_name="a"),
                _DummyEndpoint(ep_name="b"),
                _DummyEndpoint(ep_name="c"),
            ]
        )
        for name in ("a", "b", "c"):
            assert f"{DEFAULT_API_PREFIX}/{name}" in _rules(app)

    def test_blueprint_mode_registers_callable_route(self):
        blueprint = Blueprint("test_bp", __name__)
        registrar = FlaskEndpointRegistrar(blueprint=blueprint)
        registrar.register_endpoint(_DummyEndpoint(ep_name="bp_ep"))
        app = Flask(__name__)
        app.register_blueprint(blueprint)
        response = app.test_client().post("/api/bp_ep", json={})
        assert response.status_code == 200
        assert response.get_json() == {"ok": True, "params": {}}

    def test_appless_registrar_raises_on_register(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__))
        registrar._app = None  # simulate a lost application reference
        with pytest.raises(RuntimeError, match="App is not defined"):
            registrar.register_endpoint(_DummyEndpoint(ep_name="ghost"))


class TestHandlerBehavior:
    def test_get_query_params_forwarded_to_run_ep(self):
        app = _make_app(_DummyEndpoint(ep_name="get_ep", method="GET"))
        response = app.test_client().get(
            f"{DEFAULT_API_PREFIX}/get_ep", query_string={"a": "1", "b": "x"}
        )
        assert response.status_code == 200
        assert response.get_json()["params"] == {"a": "1", "b": "x"}

    def test_post_json_body_forwarded_to_run_ep(self):
        app = _make_app(_DummyEndpoint(ep_name="json_ep"))
        response = app.test_client().post(
            f"{DEFAULT_API_PREFIX}/json_ep", json={"k": [1, 2], "s": "v"}
        )
        assert response.status_code == 200
        assert response.get_json()["params"] == {"k": [1, 2], "s": "v"}

    def test_post_form_fallback_when_not_json(self):
        app = _make_app(_DummyEndpoint(ep_name="form_ep"))
        response = app.test_client().post(
            f"{DEFAULT_API_PREFIX}/form_ep", data={"f": "1"}
        )
        assert response.status_code == 200
        assert response.get_json()["params"] == {"f": "1"}

    def test_none_result_becomes_empty_object(self):
        app = _make_app(
            _DummyEndpoint(ep_name="none_ep", behavior=lambda params: None)
        )
        response = app.test_client().post(f"{DEFAULT_API_PREFIX}/none_ep")
        assert response.status_code == 200
        assert response.get_json() == {}

    def test_tuple_result_respects_status_code(self):
        app = _make_app(
            _DummyEndpoint(
                ep_name="tuple_ep",
                behavior=lambda params: ({"msg": "nope"}, 404),
            )
        )
        response = app.test_client().post(f"{DEFAULT_API_PREFIX}/tuple_ep")
        assert response.status_code == 404
        assert response.get_json() == {"msg": "nope"}

    def test_str_result_returned_verbatim(self):
        app = _make_app(
            _DummyEndpoint(ep_name="text_ep", behavior=lambda params: "plain text")
        )
        response = app.test_client().post(f"{DEFAULT_API_PREFIX}/text_ep")
        assert response.status_code == 200
        assert response.get_data(as_text=True) == "plain text"

    def test_generator_result_streamed_as_event_stream(self):
        def stream(params):
            yield "data: 1\n"
            yield "data: 2\n"

        app = _make_app(
            _DummyEndpoint(ep_name="stream_ep", method="GET", behavior=stream)
        )
        response = app.test_client().get(f"{DEFAULT_API_PREFIX}/stream_ep")
        assert response.status_code == 200
        assert response.content_type.startswith("text/event-stream")
        assert response.get_data(as_text=True) == "data: 1\ndata: 2\n"


class TestHandlerErrorMapping:
    def test_value_error_maps_to_400_with_shape(self):
        def boom(params):
            raise ValueError("bad input: value")

        app = _make_app(_DummyEndpoint(ep_name="valerr", behavior=boom))
        response = app.test_client().post(f"{DEFAULT_API_PREFIX}/valerr")
        assert response.status_code == 400
        body = response.get_json()
        assert body["status"] is False
        assert body["error"]["type"] == "invalid_request_error"
        assert body["error"]["param"] is None
        assert body["error"]["code"] == 400
        assert "bad input: value" in body["error"]["message"]

    def test_value_error_message_is_sanitized(self):
        def boom(params):
            raise ValueError(
                "failed to reach http://10.1.2.3:8080/x?api_token=zzz "
                "host='10.1.2.3'"
            )

        app = _make_app(_DummyEndpoint(ep_name="valerr2", behavior=boom))
        body = app.test_client().post(f"{DEFAULT_API_PREFIX}/valerr2").get_json()
        message = body["error"]["message"]
        assert "10.1.2.3" not in message
        assert "zzz" not in message

    def test_generic_exception_maps_to_500(self):
        def boom(params):
            raise RuntimeError("db down http://10.9.8.7:1234/secret")

        app = _make_app(_DummyEndpoint(ep_name="boom", behavior=boom))
        response = app.test_client().post(f"{DEFAULT_API_PREFIX}/boom")
        assert response.status_code == 500
        assert response.get_json() == {
            "error": "internal_error",
            "details": "An internal error occurred",
        }

    def test_param_extraction_failure_maps_to_400(self, monkeypatch):
        app = _make_app(_DummyEndpoint(ep_name="extract", method="GET"))

        def _exploding(method):
            raise RuntimeError(
                "crash at http://192.168.0.9:9000/secret?token=abc123"
            )

        monkeypatch.setattr(
            FlaskEndpointRegistrar, "_extract_params", staticmethod(_exploding)
        )
        response = app.test_client().get(f"{DEFAULT_API_PREFIX}/extract")
        assert response.status_code == 400
        body = response.get_json()
        assert body["error"] == "bad_request"
        assert "192.168.0.9" not in body["details"]
        assert "abc123" not in body["details"]


class TestExtractParams:
    def test_get_uses_query_args(self):
        app = Flask(__name__)
        with app.test_request_context("/x?a=1&b=2", method="GET"):
            assert FlaskEndpointRegistrar._extract_params("GET") == {
                "a": "1",
                "b": "2",
            }

    def test_post_prefers_json_payload(self):
        app = Flask(__name__)
        with app.test_request_context("/x", method="POST", json={"j": 1}):
            assert FlaskEndpointRegistrar._extract_params("POST") == {"j": 1}

    def test_post_falls_back_to_form_data(self):
        app = Flask(__name__)
        with app.test_request_context("/x", method="POST", data={"f": "1"}):
            assert FlaskEndpointRegistrar._extract_params("post") == {"f": "1"}


class TestContextManager:
    def test_enter_returns_self(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__))
        with registrar as returned:
            assert returned is registrar

    def test_exit_returns_false(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__))
        assert registrar.__exit__(None, None, None) is False

    def test_exit_does_not_swallow_exceptions(self):
        registrar = FlaskEndpointRegistrar(app=Flask(__name__))
        with pytest.raises(RuntimeError, match="kaboom"):
            with registrar:
                raise RuntimeError("kaboom")
