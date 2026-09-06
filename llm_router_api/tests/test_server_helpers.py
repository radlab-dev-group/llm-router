"""
Unit tests for ``llm_router_api.core.server`` helpers.

Covers the Flask logger handler helper (idempotent FileHandler
installation), the shutdown-hook installer (signal handlers are
restored after each test) and the ImportError paths of the
Gunicorn/Waitress runners (packages are not installed in the test
environment).
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import logging  # noqa: E402
import signal  # noqa: E402
from unittest import mock  # noqa: E402

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import llm_router_api.core.server as server_module  # noqa: E402
from llm_router_api.core.server import (  # noqa: E402
    _ensure_flask_logger_handlers,
    install_shutdown_hooks,
    run_gunicorn_server,
    run_waitress_server,
)


class TestEnsureFlaskLoggerHandlers:
    def test_adds_one_file_handler(self, tmp_path, monkeypatch):
        log_file = tmp_path / "test-app.log"
        monkeypatch.setattr(
            server_module, "REST_API_LOG_FILE_NAME", str(log_file)
        )
        app = Flask(__name__)
        _ensure_flask_logger_handlers(app)
        file_handlers = [
            h for h in app.logger.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert log_file.exists()

    def test_second_call_is_idempotent(self, tmp_path, monkeypatch):
        log_file = tmp_path / "test-app.log"
        monkeypatch.setattr(
            server_module, "REST_API_LOG_FILE_NAME", str(log_file)
        )
        app = Flask(__name__)
        _ensure_flask_logger_handlers(app)
        _ensure_flask_logger_handlers(app)
        file_handlers = [
            h for h in app.logger.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1

    def test_existing_file_handler_not_duplicated(self):
        app = Flask(__name__)
        existing = logging.FileHandler(os.devnull)
        app.logger.addHandler(existing)
        _ensure_flask_logger_handlers(app)
        file_handlers = [
            h for h in app.logger.handlers
            if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert existing in file_handlers


class TestInstallShutdownHooks:
    def _save_restore(self):
        orig_term = signal.getsignal(signal.SIGTERM)
        orig_int = signal.getsignal(signal.SIGINT)
        return orig_term, orig_int

    def _restore(self, orig_term, orig_int):
        signal.signal(signal.SIGTERM, orig_term)
        signal.signal(signal.SIGINT, orig_int)

    def test_installs_non_default_handlers(self):
        engine = mock.Mock()
        orig_term, orig_int = self._save_restore()
        try:
            install_shutdown_hooks(engine)
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
            assert signal.getsignal(signal.SIGINT) is not signal.SIG_DFL
        finally:
            self._restore(orig_term, orig_int)

    def test_safe_to_call_twice(self):
        engine = mock.Mock()
        orig_term, orig_int = self._save_restore()
        try:
            install_shutdown_hooks(engine)
            install_shutdown_hooks(engine)
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
        finally:
            self._restore(orig_term, orig_int)

    def test_handler_stops_engine_and_exits(self):
        engine = mock.Mock()
        orig_term, orig_int = self._save_restore()
        try:
            install_shutdown_hooks(engine)
            handler = signal.getsignal(signal.SIGTERM)
            with pytest.raises(SystemExit) as exc_info:
                handler(signal.SIGTERM, None)
            assert exc_info.value.code == 128 + signal.SIGTERM
            engine.stop.assert_called_once()
            # the handler restores the default disposition itself
            assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
        finally:
            self._restore(orig_term, orig_int)


class TestServerRunners:
    def test_gunicorn_not_installed(self):
        with pytest.raises(ImportError, match="Gunicorn is not installed"):
            run_gunicorn_server("127.0.0.1", 8080)

    def test_waitress_not_installed(self):
        with pytest.raises(ImportError, match="Waitress is not installed"):
            run_waitress_server("127.0.0.1", 8080)
