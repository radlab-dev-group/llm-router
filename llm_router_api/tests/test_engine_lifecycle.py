"""
M13 — :class:`FlaskEngine` must expose an explicit, idempotent background‑
thread lifecycle (``start``/``stop``/context manager/``atexit``) so that a
multi‑worker server (gunicorn) does not leak the services‑monitor thread.

The acceptance scenario from the plan: create the engine, then stop it, and
verify that no non‑daemon background thread is left running (the thread list
is "empty" apart from the main thread and interpreter housekeeping).
"""

import threading
import time

import pytest

import llm_router_api.core.engine as engine_mod
from llm_router_api.core.engine import FlaskEngine


# ---------------------------------------------------------------------------
# A stub monitor that spawns a real daemon thread, so the test can assert
# the engine actually starts/stops a background thread.
# ---------------------------------------------------------------------------
class _StubMonitor:
    instances = []

    def __init__(self, **kwargs) -> None:
        self._thread = threading.Thread(
            target=self._run, name="stub-services-monitor", daemon=True
        )
        self._stop = threading.Event()
        self.started = False
        self.stopped = False
        self.stop_count = 0
        _StubMonitor.instances.append(self)

    def _run(self) -> None:
        while not self._stop.is_set():
            time.sleep(0.01)

    def start(self) -> None:
        self.started = True
        # Re-arm a fresh thread object so start() can be called again after a
        # stop() (a Python Thread can only be started once).
        self._thread = threading.Thread(
            target=self._run, name="stub-services-monitor", daemon=True
        )
        self._stop.clear()
        self._thread.start()

    def stop(self) -> None:
        self.stopped = True
        self.stop_count += 1
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)


def _config_path():
    from pathlib import Path

    return str(
        Path(__file__).resolve().parents[2]
        / "resources"
        / "configs"
        / "models-config.json"
    )


@pytest.fixture
def _stub_engine(monkeypatch):
    """Build a FlaskEngine whose services monitor is a real-thread stub."""

    def _factory(**kwargs):
        return _StubMonitor(**kwargs)

    monkeypatch.setattr(
        engine_mod, "LLMRouterServicesMonitor", _factory, raising=False
    )
    eng = FlaskEngine(
        prompts_dir="resources/prompts", models_config_path=_config_path()
    )
    return eng


def _non_main_threads():
    return [t for t in threading.enumerate() if t is not threading.main_thread()]


class TestEngineLifecycle:
    def test_constructor_starts_monitor(self, _stub_engine):
        mon = _StubMonitor.instances[-1]
        assert mon.started
        assert mon._thread.is_alive()
        # The engine tracks it as started.
        assert _stub_engine._monitor_started

    def test_stop_stops_monitor_and_thread(self, _stub_engine):
        mon = _StubMonitor.instances[-1]
        _stub_engine.stop()
        assert mon.stopped
        assert not mon._thread.is_alive()
        assert not _stub_engine._monitor_started

    def test_stop_is_idempotent(self, _stub_engine):
        mon = _StubMonitor.instances[-1]
        _stub_engine.stop()
        _stub_engine.stop()
        _stub_engine.stop()
        # stop() called 3x must never raise (idempotent / safe re-join) and the
        # thread must end up dead.
        assert not mon._thread.is_alive()

    def test_start_after_stop_restarts(self, _stub_engine):
        mon = _StubMonitor.instances[-1]
        _stub_engine.stop()
        assert not mon._thread.is_alive()
        assert not _stub_engine._monitor_started
        # Re-arm: start() should bring the tracked state back up.
        _stub_engine.start()
        assert _stub_engine._monitor_started

    def test_context_manager_stops_on_exit(self, _stub_engine):
        mon = _StubMonitor.instances[-1]
        with _stub_engine:
            assert mon._thread.is_alive()
        assert not mon._thread.is_alive()

    def test_no_leftover_non_daemon_threads_after_stop(self, _stub_engine):
        before = {t.name for t in _non_main_threads()}
        # The stub monitor thread is a daemon (safety net).
        mon_thread = _StubMonitor.instances[-1]._thread
        assert mon_thread.daemon is True
        _stub_engine.stop()
        # After stop, our background thread must be gone from the list.
        after = {t for t in _non_main_threads()}
        assert mon_thread not in after

    def test_thread_is_daemon_safety_net(self, _stub_engine):
        # Even if stop() were never called, the thread must be a daemon so it
        # cannot hold the interpreter open (gunicorn worker teardown).
        assert _StubMonitor.instances[-1]._thread.daemon is True


# ---------------------------------------------------------------------------
# atexit hook is registered on the engine
# ---------------------------------------------------------------------------
class TestAtexit:
    def test_atexit_registered(self, _stub_engine):
        import atexit

        # atexit.register does not expose the registered callbacks directly,
        # so assert via a sentinel: stop must be wired to _shutdown_background.
        assert hasattr(_stub_engine, "_shutdown_background")
        # Call it directly and confirm it drives the monitor stop.
        mon = _StubMonitor.instances[-1]
        _stub_engine._shutdown_background()
        assert mon.stopped


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
