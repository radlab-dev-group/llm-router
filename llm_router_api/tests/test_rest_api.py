"""
Unit tests for ``llm_router_api.rest_api``.

Covers CLI argument parsing and the server dispatch logic in ``main``.
The server runners are mocked in the ``llm_router_api.rest_api`` namespace
so no server is ever started.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import sys  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402

import llm_router_api.rest_api as rest_api_module  # noqa: E402
from llm_router_api.base.constants import (  # noqa: E402
    LLM_ROUTER_API_TIMEOUT,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_THREADS_COUNT,
    SERVER_WORKERS_CLASS,
    SERVER_WORKERS_COUNT,
)


class TestParseArgs:
    def test_defaults(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api"])
        args = rest_api_module._parse_args()
        assert args.gunicorn is False
        assert args.waitress is False
        assert args.host == SERVER_HOST
        assert args.port == SERVER_PORT
        assert args.workers == SERVER_WORKERS_COUNT
        assert args.threads == SERVER_THREADS_COUNT

    def test_gunicorn_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api", "--gunicorn"])
        args = rest_api_module._parse_args()
        assert args.gunicorn is True
        assert args.waitress is False

    def test_waitress_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api", "--waitress"])
        args = rest_api_module._parse_args()
        assert args.waitress is True
        assert args.gunicorn is False

    def test_port_override(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api", "--port", "9999"])
        args = rest_api_module._parse_args()
        assert args.port == 9999

    def test_host_and_workers(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["rest_api", "--host", "0.0.0.0", "--workers", "4"]
        )
        args = rest_api_module._parse_args()
        assert args.host == "0.0.0.0"
        assert args.workers == 4


class TestMainDispatch:
    def test_gunicorn_dispatch(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api", "--gunicorn"])
        with (
            mock.patch.object(rest_api_module, "run_gunicorn_server") as gunicorn,
            mock.patch.object(rest_api_module, "run_waitress_server") as waitress,
            mock.patch.object(rest_api_module, "run_flask_server") as flask,
        ):
            rest_api_module.main()
        gunicorn.assert_called_once_with(
            host=SERVER_HOST,
            port=SERVER_PORT,
            workers=SERVER_WORKERS_COUNT,
            threads=SERVER_THREADS_COUNT,
            timeout=LLM_ROUTER_API_TIMEOUT,
            worker_class=SERVER_WORKERS_CLASS,
        )
        waitress.assert_not_called()
        flask.assert_not_called()

    def test_waitress_dispatch(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api", "--waitress"])
        with (
            mock.patch.object(rest_api_module, "run_gunicorn_server") as gunicorn,
            mock.patch.object(rest_api_module, "run_waitress_server") as waitress,
            mock.patch.object(rest_api_module, "run_flask_server") as flask,
        ):
            rest_api_module.main()
        waitress.assert_called_once_with(
            host=SERVER_HOST, port=SERVER_PORT, threads=SERVER_WORKERS_COUNT
        )
        gunicorn.assert_not_called()
        flask.assert_not_called()

    def test_default_flask_dispatch(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api"])
        monkeypatch.setattr(rest_api_module, "SERVER_TYPE", "flask")
        with (
            mock.patch.object(rest_api_module, "run_gunicorn_server") as gunicorn,
            mock.patch.object(rest_api_module, "run_waitress_server") as waitress,
            mock.patch.object(rest_api_module, "run_flask_server") as flask,
        ):
            rest_api_module.main()
        flask.assert_called_once_with(
            host=SERVER_HOST, port=SERVER_PORT, debug=False
        )
        gunicorn.assert_not_called()
        waitress.assert_not_called()

    def test_server_exception_propagates(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rest_api", "--gunicorn"])
        with mock.patch.object(
            rest_api_module,
            "run_gunicorn_server",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                rest_api_module.main()
