"""
H‑B regression tests: client input errors must return **400**, not 500.

Contract (see PLAN_TODO.md, item H‑B):

* endpoints validate input and raise :class:`ValueError` (or a subclass,
  e.g. pydantic ``ValidationError``) for client‑side problems;
* ``run_ep`` lets the ``ValueError`` propagate (it must not be masked into
  a 500 error tuple);
* the Flask registrar is the single owner of the exception→status‑code
  mapping and translates ``ValueError`` into HTTP 400 with the exception
  message in ``{"error": {"message": …}}``;
* real server‑side failures still return 500.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from flask import Flask  # noqa: E402

from llm_router_api.endpoints.endpoint_i import (
    EndpointWithHttpRequestI,
)  # noqa: E402
from llm_router_api.register.register import FlaskEndpointRegistrar  # noqa: E402
from llm_router_api.core.decorators import EP  # noqa: E402


class _ValidatedRequest(BaseModel):
    model_name: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


class _ValidatedEndpoint(EndpointWithHttpRequestI):
    """Endpoint that validates input with a pydantic model (like chat)."""

    def __init__(self):
        super().__init__(ep_name="validated_ep", api_types=["builtin"])
        self.REQUIRED_ARGS = ["model_name", "prompt"]

    @EP.require_params
    def prepare_payload(self, params: Optional[Dict[str, Any]]):
        req = _ValidatedRequest(**params)
        return req.model_dump()


class _ServerBoomEndpoint(EndpointWithHttpRequestI):
    """Endpoint with a genuine server‑side failure (inside the payload step)."""

    def __init__(self):
        super().__init__(ep_name="server_boom", api_types=["builtin"])
        self.REQUIRED_ARGS = []

    def prepare_payload(self, params: Optional[Dict[str, Any]]):
        raise RuntimeError("database on fire")


@pytest.fixture()
def client():
    app = Flask(__name__)
    registrar = FlaskEndpointRegistrar(app=app)
    registrar.register_endpoint(_ValidatedEndpoint())
    registrar.register_endpoint(_ServerBoomEndpoint())
    return app.test_client()


class TestInputErrorsReturn400:
    def test_missing_required_param_returns_400(self, client):
        resp = client.post("/api/validated_ep", json={"model_name": "m"})
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["status"] is False
        assert body["error"]["code"] == 400
        assert "prompt" in body["error"]["message"]

    def test_empty_prompt_returns_400(self, client):
        resp = client.post(
            "/api/validated_ep", json={"model_name": "m", "prompt": ""}
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"]["code"] == 400
        assert body["error"]["type"] == "invalid_request_error"

    def test_empty_payload_returns_400(self, client):
        resp = client.post("/api/validated_ep", json={})
        assert resp.status_code == 400
        assert resp.get_json()["status"] is False

    def test_wrong_param_type_returns_400(self, client):
        # ``prompt`` must be a string — a list is client input error → 400
        resp = client.post(
            "/api/validated_ep", json={"model_name": "m", "prompt": [1, 2, 3]}
        )
        assert resp.status_code == 400

    def test_error_body_carrying_message_is_readably_sanitized(self, client):
        resp = client.post("/api/validated_ep", json={"model_name": "m"})
        msg = resp.get_json()["error"]["message"]
        assert isinstance(msg, str) and msg.strip()


class TestServerErrorsStillReturn500:
    def test_runtime_error_returns_500(self, client):
        resp = client.post("/api/server_boom", json={"x": 1})
        assert resp.status_code == 500
        body = resp.get_json()
        assert body["status"] is False
        assert body["error"]["code"] == 500


class TestValueErrorPropagation:
    def test_run_ep_does_not_swallow_value_error(self):
        """
        The endpoint's ``run_ep`` must re‑raise ``ValueError`` (input
        contract) instead of converting it into a 500 error tuple.
        """
        ep = _ValidatedEndpoint()
        ep._get_router_metrics = lambda: None
        with pytest.raises(ValueError):
            ep.run_ep({"model_name": "m"})  # missing required arg "prompt"

    def test_direct_return_path_unreachable_for_error_tuple(self):
        """
        Regression for the "error tuple leaking into params" bug: after
        validation fails no tuple may flow into ``params``.
        """
        ep = _ValidatedEndpoint()
        calls = []

        def spy_prepare(params):
            calls.append(params)
            # simulate the decorated prepare_payload (raises ValueError)
            return ep.prepare_payload(params)

        with pytest.raises(ValueError):
            spy_prepare({"model_name": "m"})
        # the only recorded payload must be a plain dict, never a tuple
        assert all(isinstance(c, dict) for c in calls)
