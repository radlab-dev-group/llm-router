"""
Tests for the ``llm-router server`` subcommand (run/stop/reload lifecycle).

Real server startups are avoided; ``stop``/``reload`` are exercised against
dummy *detached* processes (double-forked so they are not children of the
test process and thus never linger as zombies), and ``run`` is tested
through its "already running" guard. PID-file helpers and the
environment-defaults helper are tested directly.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from pathlib import Path
from typing import Tuple

import pytest

from llm_router_cli.cli import main
from llm_router_cli.cli.commands import server as server_module
from llm_router_cli.cli.commands.server import (
    ServerCommand,
    _is_sensitive,
    _paint,
    _resolve_color,
    colorize_line,
    get_alive_pid,
    pid_alive,
    read_pid_file,
    remove_pid_file,
    tail_lines,
    write_pid_file,
)
from llm_router_cli.cli.env_defaults import (
    DEFAULT_ENV,
    apply_default_env,
)

# ---- fixtures / helpers ----------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_env():
    """``_apply_start_env`` mutates ``os.environ``; never leak that into a test."""
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    """Keep every instance's state inside *tmp_path*."""
    monkeypatch.setattr(server_module, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(server_module, "DEFAULT_PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(server_module, "DEFAULT_LOG_FILE", tmp_path / "server.log")
    monkeypatch.delenv(server_module.INSTANCE_ENV_VAR, raising=False)
    return tmp_path


@pytest.fixture
def pid_file(tmp_path):
    return tmp_path / "server.pid"


def _spawn_detached(cmd, pid_out: Path) -> int:
    """Double-fork *cmd* so it is not a child of the test process."""
    first = os.fork()
    if first == 0:  # pragma: no cover - parent side is tested
        os.setsid()
        second = os.fork()
        if second == 0:  # pragma: no cover - grandchild execs the dummy
            pid_out.write_text(f"{os.getpid()}\n", encoding="utf-8")
            os.execvp(cmd[0], cmd)
            os._exit(1)
        os._exit(0)
    os.waitpid(first, 0)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            return int(pid_out.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            time.sleep(0.05)
    raise RuntimeError("dummy process did not start")


def _kill(pid: int) -> None:
    """SIGKILL *pid* and wait until it is gone."""
    os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.05)


def _wait_for(path: Path, timeout: float = 5.0) -> bool:
    """Wait until *path* shows up; used to sync with a spawned dummy process."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def _spawn_master_with_worker(
    tmp_path: Path, worker_traps_term: bool = False
) -> Tuple[int, int]:
    """
    Spawn a detached master that backgrounds a worker, like a Gunicorn tree.

    The worker keeps running when the master exits on SIGTERM (it is reparented
    to init), which is exactly the state in which a fork still holds the
    listening socket it inherited. With *worker_traps_term* the worker also
    ignores SIGTERM, standing in for a worker stuck in a request. Returns
    ``(master_pid, worker_pid)``.
    """
    worker = (
        "bash -c \"trap '' TERM; sleep 300\"" if worker_traps_term else "sleep 300"
    )
    ready = tmp_path / "master-ready"
    worker_pid_file = tmp_path / "worker.pid"
    script = (
        f'{worker} & worker=$!; echo "$worker" > {worker_pid_file}; '
        f": > {ready}; trap 'exit 0' TERM; wait"
    )
    master = _spawn_detached(["bash", "-c", script], tmp_path / "master.pid")
    assert _wait_for(ready)
    worker_pid = int(worker_pid_file.read_text(encoding="utf-8").strip())
    return master, worker_pid


def _assert_gone(*pids: int) -> None:
    """Assert *pids* released everything they held (an unreaped zombie has too)."""
    for pid in pids:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not server_module._has_exited(pid):
            time.sleep(0.05)
        assert server_module._has_exited(pid) is True


def _kill_all(*pids: int) -> None:
    """SIGKILL every one of *pids* that is still alive (test cleanup)."""
    for pid in pids:
        # 0 would mean "my whole process group" -- never signal that.
        if pid > 0 and pid_alive(pid):
            _kill(pid)


def _spawn_dead_pid() -> int:
    """Fork a child that exits immediately; return its (now dead) PID."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child exits right away
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


def _recording_start(seen: dict):
    """Stand in for ``_start``: remember the launch args instead of spawning."""

    def fake_start(args):
        seen["args"] = args
        return 0

    return staticmethod(fake_start)


# ---- help / dispatch ------------------------------------------------------


def test_bare_server_shows_help(capsys):
    assert ServerCommand.run([]) == 0
    out = capsys.readouterr().out
    for word in ("start", "stop", "reload", "status", "log"):
        assert word in out


def test_start_help_lists_flags(capsys):
    assert ServerCommand.run(["start", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in (
        "--foreground",
        "--log-file",
        "--server",
        "--host",
        "--port",
        "--models-config",
        "--debug",
        "--verbose",
        "--lb-strategy",
        "--default-lang",
        "--auth",
        "--redis-host",
        "--redis-port",
        "--redis-db",
        "--redis-password",
        "--auth-redis-host",
        "--auth-redis-port",
        "--auth-redis-db",
        "--auth-redis-password",
        "--pid-file",
        "--no-port-check",
        "--no-config-check",
        "--save-config",
        "--instance",
    ):
        assert flag in out


def test_stop_help_lists_flags(capsys):
    assert ServerCommand.run(["stop", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--force" in out
    assert "--pid-file" in out
    assert "--all" in out
    assert "-i" in out


def test_reload_help_lists_flags(capsys):
    assert ServerCommand.run(["reload", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--force" in out
    assert "--graceful" in out
    assert "--pid-file" in out
    assert "-i" in out


def test_invalid_server_choice_rejected(capsys):
    assert ServerCommand.run(["start", "--server", "uwsgi"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_dispatch_routes_each_action(monkeypatch):
    calls = []
    for name in (
        "_start",
        "_stop",
        "_reload",
        "_status",
        "_list",
        "_rm_instance",
    ):
        monkeypatch.setattr(
            ServerCommand,
            name,
            staticmethod(lambda args, _n=name: calls.append(_n) or 7),
        )
    parser = ServerCommand.build_parser()
    assert ServerCommand.dispatch(parser.parse_args(["start"])) == 7
    assert ServerCommand.dispatch(parser.parse_args(["stop"])) == 7
    assert ServerCommand.dispatch(parser.parse_args(["reload"])) == 7
    assert ServerCommand.dispatch(parser.parse_args(["status"])) == 7
    assert ServerCommand.dispatch(parser.parse_args(["list"])) == 7
    assert ServerCommand.dispatch(parser.parse_args(["rm-instance", "dev"])) == 7
    assert calls == [
        "_start",
        "_stop",
        "_reload",
        "_status",
        "_list",
        "_rm_instance",
    ]


def test_main_dispatches_server_stop(monkeypatch, pid_file, capsys):
    seen = {}

    def fake_stop(args):
        seen["args"] = args
        return 3

    monkeypatch.setattr(ServerCommand, "_stop", staticmethod(fake_stop))
    assert main(["server", "stop", "--pid-file", str(pid_file)]) == 3
    assert seen["args"].pid_file == str(pid_file)


# ---- PID-file helpers -----------------------------------------------------


def test_pid_file_roundtrip(pid_file):
    write_pid_file(pid_file, 4242)
    assert read_pid_file(pid_file) == 4242


def test_read_pid_file_missing_or_corrupt(tmp_path):
    assert read_pid_file(tmp_path / "nope.pid") is None
    bad = tmp_path / "bad.pid"
    bad.write_text("not-a-pid\n", encoding="utf-8")
    assert read_pid_file(bad) is None


def test_remove_pid_file_is_idempotent(pid_file):
    remove_pid_file(pid_file)  # missing -> no error
    write_pid_file(pid_file, 7)
    remove_pid_file(pid_file)
    assert not pid_file.exists()


def test_get_alive_pid_cleans_stale_entry(pid_file):
    write_pid_file(pid_file, _spawn_dead_pid())
    assert get_alive_pid(pid_file) is None
    assert not pid_file.exists()  # stale file cleaned up


def test_get_alive_pid_returns_live_pid(pid_file, tmp_path):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    try:
        write_pid_file(pid_file, pid)
        assert get_alive_pid(pid_file) == pid
        assert pid_file.exists()
    finally:
        _kill(pid)


def test_pid_alive_lifecycle(tmp_path):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    try:
        assert pid_alive(pid) is True
    finally:
        _kill(pid)
    assert pid_alive(pid) is False


# ---- environment defaults -------------------------------------------------


def test_apply_default_env_sets_defaults_without_overriding(monkeypatch):
    monkeypatch.delenv("LLM_ROUTER_IN_DEBUG", raising=False)
    monkeypatch.setenv("LLM_ROUTER_BALANCE_STRATEGY", "weighted")

    apply_default_env()

    assert os.environ["LLM_ROUTER_IN_DEBUG"] == "1"
    # User's shell always wins over the mirrored defaults.
    assert os.environ["LLM_ROUTER_BALANCE_STRATEGY"] == "weighted"
    # Spot-check that the mirrored set matches the production script.
    assert DEFAULT_ENV["LLM_ROUTER_SERVER_TYPE"] == "gunicorn"
    assert os.environ["LLM_ROUTER_SERVER_TYPE"] in ("gunicorn", "waitress", "flask")


def test_verbose_mode_is_off_by_default(monkeypatch):
    """Verbose mode dumps unmasked params, so the shipped default is off."""
    monkeypatch.delenv("LLM_ROUTER_VERBOSE", raising=False)

    apply_default_env()

    assert DEFAULT_ENV["LLM_ROUTER_VERBOSE"] == "0"
    assert os.environ["LLM_ROUTER_VERBOSE"] == "0"


def test_invalid_lb_strategy_rejected(capsys):
    assert ServerCommand.run(["start", "--lb-strategy", "bogus"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_nworkers_lb_strategy_accepted():
    args = ServerCommand.build_parser().parse_args(
        ["start", "--lb-strategy", "first_available_optim_nworkers"]
    )
    assert args.lb_strategy == "first_available_optim_nworkers"


def test_invalid_debug_value_rejected(capsys):
    assert ServerCommand.run(["start", "--debug", "2"]) == 2
    assert "invalid choice" in capsys.readouterr().err


# ---- start: env overrides -------------------------------------------------


def test_build_env_overrides_only_includes_given_flags():
    parser = ServerCommand.build_parser()
    args = parser.parse_args(["start"])
    assert ServerCommand.build_env_overrides(args) == {}

    args = parser.parse_args(
        [
            "start",
            "--models-config",
            "models/configs/my.json",
            "--debug",
            "1",
            "--lb-strategy",
            "weighted",
            "--default-lang",
            "en",
            "--auth",
            "1",
            "--redis-host",
            "redis.example",
            "--redis-port",
            "7000",
            "--redis-db",
            "2",
            "--redis-password",
            "pw",
            "--auth-redis-host",
            "auth-redis.example",
            "--auth-redis-port",
            "7100",
            "--auth-redis-db",
            "3",
            "--auth-redis-password",
            "apw",
        ]
    )
    assert ServerCommand.build_env_overrides(args) == {
        "LLM_ROUTER_MODELS_CONFIG": "models/configs/my.json",
        "LLM_ROUTER_IN_DEBUG": "1",
        "LLM_ROUTER_BALANCE_STRATEGY": "weighted",
        "LLM_ROUTER_DEFAULT_EP_LANGUAGE": "en",
        "LLM_ROUTER_AUTH_ENABLED": "true",
        "LLM_ROUTER_REDIS_HOST": "redis.example",
        "LLM_ROUTER_REDIS_PORT": "7000",
        "LLM_ROUTER_REDIS_DB": "2",
        "LLM_ROUTER_REDIS_PASSWORD": "pw",
        "LLM_ROUTER_AUTH_REDIS_HOST": "auth-redis.example",
        "LLM_ROUTER_AUTH_REDIS_PORT": "7100",
        "LLM_ROUTER_AUTH_REDIS_DB": "3",
        "LLM_ROUTER_AUTH_REDIS_PASSWORD": "apw",
    }


def test_start_auth_zero_maps_to_false():
    args = ServerCommand.build_parser().parse_args(["start", "--auth", "0"])
    assert ServerCommand.build_env_overrides(args) == {
        "LLM_ROUTER_AUTH_ENABLED": "false"
    }


def test_start_verbose_flag_maps_to_env_override():
    parser = ServerCommand.build_parser()
    # Without the flag the shell env / defaults keep verbose mode off.
    assert "LLM_ROUTER_VERBOSE" not in ServerCommand.build_env_overrides(
        parser.parse_args(["start"])
    )

    args = parser.parse_args(["start", "--verbose"])
    assert ServerCommand.build_env_overrides(args) == {"LLM_ROUTER_VERBOSE": "1"}


def test_start_applies_overrides_beating_shell_env(monkeypatch, tmp_path, capsys):
    captured = {}

    class FakeProc:
        pid = 4242

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = dict(os.environ)
        return FakeProc()

    monkeypatch.setattr(server_module.subprocess, "Popen", fake_popen)
    # Shell env value that the CLI flag must beat.
    monkeypatch.setenv("LLM_ROUTER_DEFAULT_EP_LANGUAGE", "pl")
    monkeypatch.setenv("LLM_ROUTER_BALANCE_STRATEGY", "balanced")

    rc = ServerCommand.run(
        [
            "start",
            "--foreground",
            "--lb-strategy",
            "weighted",
            "--default-lang",
            "en",
            "--auth",
            "1",
            "--redis-host",
            "redis.example",
            "--pid-file",
            str(tmp_path / "p.pid"),
        ]
    )
    assert rc == 0
    env = captured["env"]
    assert env["LLM_ROUTER_BALANCE_STRATEGY"] == "weighted"
    assert env["LLM_ROUTER_DEFAULT_EP_LANGUAGE"] == "en"
    assert env["LLM_ROUTER_AUTH_ENABLED"] == "true"
    assert env["LLM_ROUTER_REDIS_HOST"] == "redis.example"
    # Mirrored defaults still fill the gaps for the spawned process.
    assert env["LLM_ROUTER_SERVER_TYPE"] == "gunicorn"
    assert "llm_router_api.rest_api" in " ".join(captured["cmd"])


def test_start_foreground_writes_and_cleans_pid_file(monkeypatch, tmp_path, capsys):
    """``--foreground`` keeps a live PID file + run record while running and
    removes both when the child exits."""
    pid_file = tmp_path / "server.pid"
    observed = {}

    class FakeProc:
        pid = 7777

        def wait(self):
            # Simulate the server being up: PID file must be visible here.
            observed["pid_file"] = pid_file.read_text(encoding="utf-8").strip()
            observed["run_record_exists"] = server_module.run_file_for(
                pid_file
            ).exists()
            return 0

    def fake_popen(cmd, **kwargs):
        observed["cmd"] = cmd
        # The foreground run record must carry the app log path resolved
        # against the launch CWD (bare LLM_ROUTER_LOG_FILENAME in the shell).
        record = server_module.read_run_file(server_module.run_file_for(pid_file))
        assert record is not None
        assert record["app_log_file"] == str(Path.cwd() / "tutaj-llm-router.log")
        # The daemon log follows LLM_ROUTER_LOG_FILENAME instead of the
        # hardcoded ~/.llm-router/server.log fallback.
        assert record["log_file"] == str(Path.cwd() / "tutaj-llm-router.log")
        return FakeProc()

    monkeypatch.setattr(server_module.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("LLM_ROUTER_LOG_FILENAME", "tutaj-llm-router.log")
    rc = ServerCommand.run(["start", "--foreground", "--pid-file", str(pid_file)])
    assert rc == 0
    assert observed["pid_file"] == "7777"
    assert observed["run_record_exists"] is True
    # After the child exits, both must be cleaned up (no stale entries).
    assert not pid_file.exists()
    assert not server_module.run_file_for(pid_file).exists()
    assert "Running in foreground (pid=7777)" in capsys.readouterr().out


def test_start_log_file_defaults_to_home_when_env_unset(
    monkeypatch, tmp_path, capsys
):
    """Without ``LLM_ROUTER_LOG_FILENAME`` the daemon log falls back to
    ``~/.llm-router/server.log`` (even though the CLI later fills the shell
    env with its default ``llm-router.log``)."""
    pid_file = tmp_path / "server.pid"

    class FakeProc:
        pid = 8888

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        record = server_module.read_run_file(server_module.run_file_for(pid_file))
        assert record is not None
        assert record["log_file"] == str(server_module.DEFAULT_LOG_FILE)
        return FakeProc()

    monkeypatch.setattr(server_module.subprocess, "Popen", fake_popen)
    monkeypatch.delenv("LLM_ROUTER_LOG_FILENAME", raising=False)
    rc = ServerCommand.run(["start", "--foreground", "--pid-file", str(pid_file)])
    assert rc == 0


def test_start_explicit_log_file_beats_env(monkeypatch, tmp_path, capsys):
    """``--log-file`` always wins over ``LLM_ROUTER_LOG_FILENAME``."""
    pid_file = tmp_path / "server.pid"
    log_file = tmp_path / "custom.log"

    class FakeProc:
        pid = 8889

        def wait(self):
            return 0

    def fake_popen(cmd, **kwargs):
        record = server_module.read_run_file(server_module.run_file_for(pid_file))
        assert record is not None
        assert record["log_file"] == str(log_file)
        return FakeProc()

    monkeypatch.setattr(server_module.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("LLM_ROUTER_LOG_FILENAME", "tutaj-llm-router.log")
    rc = ServerCommand.run(
        [
            "start",
            "--foreground",
            "--log-file",
            str(log_file),
            "--pid-file",
            str(pid_file),
        ]
    )
    assert rc == 0


def test_start_foreground_propagates_exit_code_and_cleans_up(
    monkeypatch, tmp_path, capsys
):
    pid_file = tmp_path / "server.pid"

    class FakeProc:
        pid = 8888

        def wait(self):
            return 3

    monkeypatch.setattr(
        server_module.subprocess,
        "Popen",
        lambda cmd, **kwargs: FakeProc(),
    )
    rc = ServerCommand.run(["start", "--foreground", "--pid-file", str(pid_file)])
    assert rc == 3
    assert not pid_file.exists()
    assert not server_module.run_file_for(pid_file).exists()


def test_start_foreground_refuses_when_server_already_running(pid_file, capsys):
    write_pid_file(pid_file, os.getpid())  # a live PID occupies the slot
    rc = ServerCommand.run(["start", "--foreground", "--pid-file", str(pid_file)])
    assert rc == 1
    assert "already running" in capsys.readouterr().err
    # The "existing" entry is untouched by the refused start.
    assert pid_file.read_text(encoding="utf-8").strip() == str(os.getpid())


# ---- stop -----------------------------------------------------------------


def test_stop_terminates_dummy_process(pid_file, tmp_path, capsys):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 0
    finally:
        if pid_alive(pid):  # pragma: no cover - safety net
            _kill(pid)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.05)
    assert not pid_alive(pid)
    assert not pid_file.exists()
    assert "Server stopped" in capsys.readouterr().out


def test_stop_missing_pid_file(pid_file, capsys):
    assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 1
    assert "No running server found" in capsys.readouterr().err


def test_stop_stale_pid_file_cleans_and_fails(pid_file, capsys):
    write_pid_file(pid_file, _spawn_dead_pid())
    assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 1
    assert not pid_file.exists()
    assert "No running server found" in capsys.readouterr().err


def test_stop_force_sigkills_uncooperative_process(pid_file, tmp_path):
    # Ignore SIGTERM, so the default (graceful) stop would time out.
    pid = _spawn_detached(
        ["bash", "-c", "trap '' TERM; sleep 300"], tmp_path / "d.pid"
    )
    write_pid_file(pid_file, pid)

    try:
        assert (
            ServerCommand.run(["stop", "--force", "--pid-file", str(pid_file)]) == 0
        )
    finally:
        if pid_alive(pid):  # pragma: no cover - safety net
            _kill(pid)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.05)
    assert not pid_alive(pid)
    assert not pid_file.exists()


def test_stop_waits_for_the_worker_processes(pid_file, tmp_path, capsys):
    """The master is not enough: the fork that inherited the socket must go."""
    master, worker = _spawn_master_with_worker(tmp_path)
    write_pid_file(pid_file, master)

    try:
        assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 0
        # "stopped" is only true once the whole tree is gone.
        _assert_gone(master, worker)
        assert not pid_file.exists()
        assert "Server stopped" in capsys.readouterr().out
    finally:
        _kill_all(master, worker)


def test_stop_sigkills_workers_that_ignore_sigterm(
    pid_file, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(server_module, "_WORKER_GRACE_SECONDS", 0.5)
    master, worker = _spawn_master_with_worker(tmp_path, worker_traps_term=True)
    write_pid_file(pid_file, master)

    try:
        assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 0
        _assert_gone(master, worker)
        assert not pid_file.exists()
        assert "outlived the master; sending SIGKILL" in capsys.readouterr().err
    finally:
        _kill_all(master, worker)


def test_stop_treats_an_unreaped_zombie_as_stopped(pid_file, monkeypatch, capsys):
    """A zombie holds no file descriptor, so waiting for its reap is pointless.

    The dummy stays a child of the test process, which never calls ``wait()``,
    standing in for a launcher that backgrounds the server and leaves it
    unreaped: the master would answer ``kill(pid, 0)`` forever otherwise.
    """
    monkeypatch.setattr(server_module, "_STOP_GRACE_SECONDS", 10)
    proc = subprocess.Popen(["sleep", "300"])
    write_pid_file(pid_file, proc.pid)

    started = time.monotonic()
    try:
        assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 0
        assert not pid_file.exists()
        assert "Server stopped" in capsys.readouterr().out
        assert time.monotonic() - started < 5
    finally:
        proc.wait()


def test_has_exited_distinguishes_running_from_zombie():
    proc = subprocess.Popen(["sleep", "300"])
    try:
        assert server_module._has_exited(proc.pid) is False
        proc.kill()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if server_module._has_exited(proc.pid):
                break
            time.sleep(0.05)
        assert server_module._has_exited(proc.pid) is True
    finally:
        proc.wait()
    assert server_module._has_exited(proc.pid) is True


def test_stop_keeps_the_state_files_when_a_worker_survives(
    pid_file, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        server_module, "_wait_tracked_gone", lambda processes, timeout: False
    )
    master, worker = _spawn_master_with_worker(tmp_path, worker_traps_term=True)
    write_pid_file(pid_file, master)

    try:
        assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 1
        err = capsys.readouterr().err
        assert "the port may still be in use" in err
        assert str(worker) in err
        # A server that is not fully down keeps its state, so a retry (or a
        # --force stop) still knows which PID it has to clear.
        assert pid_file.exists()
    finally:
        _kill_all(master, worker)


# ---- reload (stop, then start again) ---------------------------------------


def test_reload_stops_the_server_and_starts_it_again(
    pid_file, tmp_path, monkeypatch, capsys
):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    models_config = tmp_path / "models.json"
    models_config.write_text('{"active_models": {}}', encoding="utf-8")
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "log_file": str(tmp_path / "daemon.log"),
            "models_config": str(models_config),
            "env_overrides": {
                "LLM_ROUTER_SERVER_PORT": "9111",
                "LLM_ROUTER_MODELS_CONFIG": "resources/models.json",
                "LLM_ROUTER_VERBOSE": "1",
            },
        },
    )
    seen: dict = {}
    monkeypatch.setattr(ServerCommand, "_start", _recording_start(seen))

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 0
    finally:
        if pid_alive(pid):  # pragma: no cover - safety net
            _kill(pid)

    out = capsys.readouterr().out
    assert f"Server stopped (pid={pid})" in out
    assert not pid_alive(pid)
    assert not pid_file.exists()

    started = seen["args"]
    assert started.server_command == "start"
    # the run record is deleted by the stop, so these can only come from it
    assert started.port == 9111
    assert started.verbose == 1
    assert started.models_config == str(models_config)
    assert started.log_file == str(tmp_path / "daemon.log")
    assert started.pid_file == str(pid_file)


def test_reload_keeps_the_server_up_when_the_models_config_is_broken(
    pid_file, tmp_path, monkeypatch, capsys
):
    seen: dict = {}
    monkeypatch.setattr(ServerCommand, "_start", _recording_start(seen))
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "models_config": str(tmp_path / "gone.json"),
            "env_overrides": {},
        },
    )

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 1
        err = capsys.readouterr().err
        assert "reload aborted" in err
        assert "models config" in err
        assert pid_alive(pid) is True
        assert pid_file.exists()
        assert seen == {}
    finally:
        _kill(pid)


def test_reload_graceful_sends_sighup_but_process_survives(
    pid_file, tmp_path, capsys
):
    # HUP-tolerant dummy stands in for the Gunicorn master; the marker tells
    # us the trap is in place before the signal goes out.
    ready = tmp_path / "trap-ready"
    pid = _spawn_detached(
        ["bash", "-c", f"trap '' HUP; : > {ready}; sleep 300"], tmp_path / "d.pid"
    )
    assert _wait_for(ready)
    write_pid_file(pid_file, pid)

    try:
        assert (
            ServerCommand.run(["reload", "--graceful", "--pid-file", str(pid_file)])
            == 0
        )
        out = capsys.readouterr().out
        assert "SIGHUP" in out
        assert str(pid) in out
        assert pid_alive(pid) is True
    finally:
        _kill(pid)


def test_reload_missing_pid_file(pid_file, capsys):
    assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 1
    err = capsys.readouterr().err
    assert "No running server found" in err
    assert "server start" in err


def test_reload_aborts_when_the_server_refuses_to_stop(
    pid_file, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(server_module, "_STOP_GRACE_SECONDS", 0.2)
    seen: dict = {}
    monkeypatch.setattr(ServerCommand, "_start", _recording_start(seen))
    # The marker is written *after* the trap is installed, so the reload can
    # never catch the dummy while SIGTERM still kills it (a lost race here
    # would make the stop succeed and the restart run).
    ready = tmp_path / "trap-ready"
    pid = _spawn_detached(
        ["bash", "-c", f"trap '' TERM; : > {ready}; sleep 300"], tmp_path / "d.pid"
    )
    assert _wait_for(ready)
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 1
        err = capsys.readouterr().err
        assert "reload aborted" in err
        assert "--force" in err
        assert seen == {}
        assert pid_alive(pid) is True
    finally:
        _kill(pid)


def test_reload_force_sigkills_and_starts_the_server_again(
    pid_file, tmp_path, monkeypatch
):
    seen: dict = {}
    monkeypatch.setattr(ServerCommand, "_start", _recording_start(seen))
    pid = _spawn_detached(
        ["bash", "-c", "trap '' TERM; sleep 300"], tmp_path / "d.pid"
    )
    write_pid_file(pid_file, pid)

    try:
        assert (
            ServerCommand.run(["reload", "--force", "--pid-file", str(pid_file)])
            == 0
        )
    finally:
        if pid_alive(pid):  # pragma: no cover - safety net
            _kill(pid)

    assert not pid_alive(pid)
    assert seen["args"].server_command == "start"


def test_reload_reports_a_failing_start_and_leaves_the_server_down(
    pid_file, tmp_path, monkeypatch, capsys
):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    monkeypatch.setattr(ServerCommand, "_start", staticmethod(lambda args: 1))

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 1
        err = capsys.readouterr().err
        assert "Reload incomplete" in err
        assert "server start" in err
        assert not pid_alive(pid)
    finally:
        if pid_alive(pid):  # pragma: no cover - safety net
            _kill(pid)


def test_restart_tokens_replay_the_recorded_start_flags():
    tokens = ServerCommand._restart_tokens(
        {
            "models_config": "/abs/models.json",
            "env_overrides": {
                "LLM_ROUTER_SERVER_HOST": "127.0.0.1",
                "LLM_ROUTER_SERVER_PORT": "8081",
                "LLM_ROUTER_SERVER_TYPE": "waitress",
                "LLM_ROUTER_AUTH_ENABLED": "true",
                "LLM_ROUTER_IN_DEBUG": "0",
                "LLM_ROUTER_VERBOSE": "1",
                "LLM_ROUTER_BALANCE_STRATEGY": "weighted",
                "LLM_ROUTER_REDIS_PORT": "6380",
                "LLM_ROUTER_MODELS_CONFIG": "relative/models.json",
            },
        }
    )
    args = ServerCommand.build_parser().parse_args(["start", *tokens])
    assert (args.host, args.port) == ("127.0.0.1", 8081)
    assert args.server == "waitress"
    assert args.auth == 1
    assert args.debug == 0
    assert args.verbose == 1
    assert args.lb_strategy == "weighted"
    assert args.redis_port == 6380
    # the absolute path from the record wins over the relative flag value
    assert args.models_config == "/abs/models.json"


def test_restart_tokens_drop_values_the_flags_would_reject():
    assert (
        ServerCommand._restart_tokens(
            {
                "env_overrides": {
                    "LLM_ROUTER_SERVER_PORT": "not-a-port",
                    "LLM_ROUTER_SERVER_TYPE": "uwsgi",
                    "LLM_ROUTER_BALANCE_STRATEGY": "round_robin",
                    "LLM_ROUTER_AUTH_ENABLED": "maybe",
                    "LLM_ROUTER_VERBOSE": "0",
                    "LLM_ROUTER_IN_DEBUG": "7",
                    "LLM_ROUTER_UNRELATED": "x",
                }
            }
        )
        == []
    )


def test_restart_argv_keeps_explicit_pid_file_and_daemon_log(tmp_path):
    instance = server_module.resolve_instance(argparse.Namespace())
    pid_file = tmp_path / "other.pid"
    argv = ServerCommand._restart_argv(
        instance,
        pid_file,
        {
            "log_file": str(tmp_path / "daemon.log"),
            "env_overrides": {"LLM_ROUTER_SERVER_PORT": "9000"},
        },
    )
    assert argv == [
        "start",
        "--port",
        "9000",
        "--pid-file",
        str(pid_file),
        "--log-file",
        str(tmp_path / "daemon.log"),
    ]


def test_reload_waits_for_the_workers_before_starting(
    pid_file, tmp_path, monkeypatch, capsys
):
    """``start`` must not run while a fork could still be holding the port."""
    master, worker = _spawn_master_with_worker(tmp_path)
    write_pid_file(pid_file, master)
    observed: dict = {}

    def fake_start(args):
        # Nothing may still hold the port when the start half begins.
        observed["master_holds_on"] = not server_module._has_exited(master)
        observed["worker_holds_on"] = not server_module._has_exited(worker)
        return 0

    monkeypatch.setattr(ServerCommand, "_start", staticmethod(fake_start))

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 0
    finally:
        _kill_all(master, worker)

    assert observed == {"master_holds_on": False, "worker_holds_on": False}
    assert "starting the server again" in capsys.readouterr().out


def test_reload_aborts_when_a_worker_survives_the_stop(
    pid_file, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        server_module, "_wait_tracked_gone", lambda processes, timeout: False
    )
    seen: dict = {}
    monkeypatch.setattr(ServerCommand, "_start", _recording_start(seen))
    master, worker = _spawn_master_with_worker(tmp_path, worker_traps_term=True)
    write_pid_file(pid_file, master)

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 1
        err = capsys.readouterr().err
        assert "reload aborted" in err
        assert "--force" in err
        assert seen == {}
    finally:
        _kill_all(master, worker)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc")
def test_process_tree_reaches_grandchildren(tmp_path):
    """A two-level fork is captured in full, start time included."""
    ready = tmp_path / "grandchild-ready"
    worker_pid_file = tmp_path / "grandchild.pid"
    proc = subprocess.Popen(
        [
            "bash",
            "-c",
            f"sleep 300 & echo $! > {worker_pid_file}; : > {ready}; wait",
        ]
    )
    grandchild = 0
    try:
        assert _wait_for(ready)
        grandchild = int(worker_pid_file.read_text(encoding="utf-8").strip())
        tree = {item.pid: item for item in server_module.process_tree(os.getpid())}
        assert proc.pid in tree
        assert grandchild in tree
        assert tree[grandchild].start_ticks is not None
        assert tree[grandchild].still_same() is True
        # A PID that changed hands is no longer the process that was captured.
        assert server_module.TrackedPid(grandchild, -1).still_same() is False
    finally:
        _kill_all(grandchild, proc.pid)
        proc.wait()


def test_restart_argv_carries_the_named_instance(tmp_path):
    """Losing ``-i`` would restart ``default``: another config.env and PID file."""
    named = server_module.resolve_instance(argparse.Namespace(instance="dev1"))
    argv = ServerCommand._restart_argv(named, named.pid_file, {"env_overrides": {}})
    assert argv == ["start", "--instance", "dev1"]

    default = server_module.resolve_instance(argparse.Namespace())
    assert ServerCommand._restart_argv(
        default, default.pid_file, {"env_overrides": {}}
    ) == ["start"]


def test_reload_restarts_the_same_instance_with_the_recorded_environment(
    state_home, monkeypatch, capsys
):
    """A launch configured by env vars has no flags to replay -- the recorded
    environment is all ``reload`` has to go by."""
    instance = server_module.resolve_instance(
        argparse.Namespace(instance="localhost-dev")
    )
    pid = _spawn_detached(["sleep", "300"], state_home / "d.pid")
    write_pid_file(instance.pid_file, pid)
    server_module.write_run_file(
        instance.run_file,
        {
            "env_overrides": {},
            "env": {
                "LLM_ROUTER_SERVER_PORT": "8081",
                "LLM_ROUTER_MODELS_CONFIG": "/srv/models.json",
                "LLM_ROUTER_AUTH_ENABLED": "1",
            },
        },
    )
    seen: dict = {}

    def fake_start(args):
        seen["args"] = args
        return 0

    monkeypatch.setattr(ServerCommand, "_start", staticmethod(fake_start))

    try:
        code = ServerCommand.run(["reload", "-i", "localhost-dev"])
    finally:
        _kill_all(pid)

    assert code == 0
    restarted = seen["args"]
    assert restarted.instance == "localhost-dev"
    assert restarted.restart_env["LLM_ROUTER_SERVER_PORT"] == "8081"
    assert restarted.restart_env["LLM_ROUTER_AUTH_ENABLED"] == "1"


def test_reloaded_environment_stays_below_config_env_and_the_shell(
    state_home, monkeypatch
):
    """The recorded env only fills what nothing else declares."""
    instance = server_module.resolve_instance(argparse.Namespace(instance="dev1"))
    instance.ensure_dir()
    instance.config_env.write_text("LLM_ROUTER_SERVER_PORT=9100\n", encoding="utf-8")
    monkeypatch.setenv("LLM_ROUTER_REDIS_HOST", "shell-host")
    monkeypatch.delenv("LLM_ROUTER_BALANCE_STRATEGY", raising=False)
    args = ServerCommand.build_parser().parse_args(["start", "-i", "dev1"])
    args.restart_env = {
        "LLM_ROUTER_SERVER_PORT": "8081",
        "LLM_ROUTER_REDIS_HOST": "record-host",
        "LLM_ROUTER_BALANCE_STRATEGY": "first_available_optim",
    }

    ServerCommand._apply_start_env(args, instance)

    assert os.environ["LLM_ROUTER_SERVER_PORT"] == "9100"
    assert os.environ["LLM_ROUTER_REDIS_HOST"] == "shell-host"
    assert os.environ["LLM_ROUTER_BALANCE_STRATEGY"] == "first_available_optim"


def test_start_without_a_record_ignores_the_recorded_layer(state_home, monkeypatch):
    """Plain ``start`` has no ``restart_env`` and keeps the plain defaults."""
    instance = server_module.resolve_instance(argparse.Namespace(instance="dev2"))
    monkeypatch.delenv("LLM_ROUTER_SERVER_PORT", raising=False)
    args = ServerCommand.build_parser().parse_args(["start", "-i", "dev2"])

    ServerCommand._apply_start_env(args, instance)

    assert (
        os.environ["LLM_ROUTER_SERVER_PORT"] == DEFAULT_ENV["LLM_ROUTER_SERVER_PORT"]
    )


def test_foreground_run_leaves_a_successor_pid_file_alone(
    monkeypatch, tmp_path, capsys
):
    """A reload that already started the next server must not be cleaned up."""
    pid_file = tmp_path / "server.pid"

    class FakeProc:
        pid = 4242

        def wait(self):
            # The reload of this instance wrote its own PID while we waited.
            write_pid_file(pid_file, 9999)
            return 0

    monkeypatch.setattr(
        server_module.subprocess, "Popen", lambda cmd, **kwargs: FakeProc()
    )
    rc = ServerCommand.run(["start", "--foreground", "--pid-file", str(pid_file)])

    assert rc == 0
    assert read_pid_file(pid_file) == 9999


# ---- status ---------------------------------------------------------------


def test_status_reports_running_server(pid_file, tmp_path, capsys):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 0
        out = capsys.readouterr().out
        assert "running" in out
        assert str(pid) in out
        assert str(pid_file) in out
    finally:
        _kill(pid)


def test_status_reports_not_running(pid_file, capsys):
    assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 1
    assert "not running" in capsys.readouterr().out.lower()


def test_status_cleans_stale_pid_file(pid_file, capsys):
    write_pid_file(pid_file, _spawn_dead_pid())
    assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 1
    assert not pid_file.exists()
    assert "not running" in capsys.readouterr().out.lower()


# ---- run record (``<pidfile>.run`` launch parameters) -----------------------


def test_run_file_for_appends_suffix(pid_file):
    assert server_module.run_file_for(pid_file) == pid_file.parent / (
        pid_file.name + ".run"
    )


def test_run_file_roundtrip(tmp_path):
    path = tmp_path / "server.pid.run"
    record = {"command": ["a", "b"], "env_overrides": {"X": "1"}}
    server_module.write_run_file(path, record)
    assert server_module.read_run_file(path) == record
    assert server_module.read_run_file(tmp_path / "missing.run") is None
    path.write_text("not json", encoding="utf-8")
    assert server_module.read_run_file(path) is None


def test_build_run_record_captures_params():
    import argparse

    args = argparse.Namespace(models_config="/tmp/custom.json", debug=1, auth=1)
    full_env = {
        "LLM_ROUTER_MODELS_CONFIG": "/tmp/custom.json",
        "LLM_ROUTER_IN_DEBUG": "1",
        "LLM_ROUTER_AUTH_ENABLED": "true",
        "LLM_ROUTER_SERVER_TYPE": "gunicorn",
        "LLM_ROUTER_LOG_LEVEL": "INFO",
    }
    record = ServerCommand.build_run_record(
        Path("/p/server.pid"),
        Path("/p/server.log"),
        ["python3", "-m", "llm_router_api.rest_api", "--port", "8080"],
        args,
        env=full_env,
    )
    assert record["command"] == [
        "python3",
        "-m",
        "llm_router_api.rest_api",
        "--port",
        "8080",
    ]
    assert record["log_file"] == "/p/server.log"
    assert record["server"] in ("gunicorn", "waitress", "flask")
    # The app's own log (no LLM_ROUTER_LOG_FILENAME in the env snapshot ->
    # default llm-router.log, a relative name) is recorded as an absolute
    # path anchored to the CWD from which the server was started.
    assert record["app_log_file"].endswith("llm-router.log")
    assert os.path.isabs(record["app_log_file"])
    # The models config (already absolute in the env snapshot) is recorded as-is.
    assert record["models_config"] == "/tmp/custom.json"
    # The full LLM_ROUTER_* env is recorded, not just the CLI overrides.
    assert record["env"] == full_env
    assert record["env_overrides"] == {
        "LLM_ROUTER_MODELS_CONFIG": "/tmp/custom.json",
        "LLM_ROUTER_IN_DEBUG": "1",
        "LLM_ROUTER_AUTH_ENABLED": "true",
    }


def test_build_run_record_anchors_relative_models_config():
    """A relative ``LLM_ROUTER_MODELS_CONFIG`` is anchored to the launch CWD."""
    import argparse

    record = ServerCommand.build_run_record(
        Path("/p/server.pid"),
        Path("/p/server.log"),
        ["python3"],
        argparse.Namespace(),
        env={"LLM_ROUTER_MODELS_CONFIG": "resources/configs/models.json"},
    )
    assert record["models_config"] == str(
        Path.cwd() / "resources/configs/models.json"
    )


def test_build_run_record_models_config_absent():
    """No ``LLM_ROUTER_MODELS_CONFIG`` -> empty recorded path (row hidden)."""
    import argparse

    record = ServerCommand.build_run_record(
        Path("/p/server.pid"),
        Path("/p/server.log"),
        ["python3"],
        argparse.Namespace(),
        env={},
    )
    assert record["models_config"] == ""


def test_build_run_record_relative_log_filename_anchored_to_cwd(
    tmp_path, monkeypatch
):
    """A bare file name (no directory) lands in the CWD at launch time."""
    import argparse

    monkeypatch.chdir(tmp_path)
    record = ServerCommand.build_run_record(
        Path("/p/server.pid"),
        Path("/p/server.log"),
        ["python3"],
        argparse.Namespace(),
        env={"LLM_ROUTER_LOG_FILENAME": "my-app.log"},
    )
    assert record["app_log_file"] == str(tmp_path / "my-app.log")


def test_build_run_record_absolute_log_filename_kept():
    import argparse

    record = ServerCommand.build_run_record(
        Path("/p/server.pid"),
        Path("/p/server.log"),
        ["python3"],
        argparse.Namespace(),
        env={"LLM_ROUTER_LOG_FILENAME": "/var/log/llm-router/app.log"},
    )
    assert record["app_log_file"] == "/var/log/llm-router/app.log"


def test_resolve_app_log_path_defaults():
    assert server_module.resolve_app_log_path({}) == str(
        Path.cwd() / "llm-router.log"
    )
    assert server_module.resolve_app_log_path(
        {"LLM_ROUTER_LOG_FILENAME": ""}
    ) == str(Path.cwd() / "llm-router.log")


def test_collect_env_snapshots_all_prefixed_vars(monkeypatch):
    from llm_router_lib.core.constants import ENV_PREFIX

    monkeypatch.delenv("LLM_ROUTER_UNSET", raising=False)
    # A non-prefixed var must be excluded from the snapshot.
    monkeypatch.setenv("UNRELATED_VAR", "x")
    monkeypatch.setenv(f"{ENV_PREFIX}ALPHA", "1")
    monkeypatch.setenv(f"{ENV_PREFIX}BETA", "2")

    env = server_module.collect_env()
    assert env[f"{ENV_PREFIX}ALPHA"] == "1"
    assert env[f"{ENV_PREFIX}BETA"] == "2"
    assert "UNRELATED_VAR" not in env
    assert all(key.startswith(ENV_PREFIX) for key in env)
    # Sorted for stable, diffable records.
    assert list(env) == sorted(env)


def test_collect_env_uses_shared_prefix():
    """The snapshot must be keyed off the library's ENV_PREFIX constant."""
    from llm_router_lib.core.constants import ENV_PREFIX

    assert ENV_PREFIX == "LLM_ROUTER_"


def test_status_shows_run_record(pid_file, tmp_path, capsys):
    env_snapshot = {
        "LLM_ROUTER_MODELS_CONFIG": "/tmp/custom.json",
        "LLM_ROUTER_SERVER_TYPE": "gunicorn",
        "LLM_ROUTER_LOG_LEVEL": "INFO",
        "LLM_ROUTER_SERVER_HOST": "0.0.0.0",
        "LLM_ROUTER_SERVER_PORT": "8080",
    }
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "started_at": "2026-01-01T00:00:00",
            "server": "gunicorn",
            "command": [
                "python3",
                "-m",
                "llm_router_api.rest_api",
                "--port",
                "8080",
            ],
            "log_file": str(tmp_path / "srv.log"),
            # Full snapshot is present; env_overrides is the CLI subset.
            "env": env_snapshot,
            "env_overrides": {"LLM_ROUTER_MODELS_CONFIG": "/tmp/custom.json"},
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert (
            ServerCommand.run(["status", "--pid-file", str(pid_file), "--show-env"])
            == 0
        )
        out = capsys.readouterr().out
        assert "All good" in out
        assert "gunicorn" in out
        assert "--port 8080" in out
        # Host / port / models-config are surfaced in the Details section.
        assert "Host" in out
        assert "Port" in out
        assert "Models config" in out
        assert "0.0.0.0" in out
        assert "8080" in out
        assert "Environment" in out
        assert "LLM_ROUTER_MODELS_CONFIG" in out
        assert "/tmp/custom.json" in out
        assert "LLM_ROUTER_LOG_LEVEL" in out
        # "Log" is the app's own file (no LLM_ROUTER_LOG_FILENAME in the env
        # snapshot -> default fallback).
        assert "llm-router.log" in out
    finally:
        _kill(pid)


def test_status_log_row_shows_app_log_from_env(pid_file, tmp_path, capsys):
    """``Log`` must reflect the app's own file (``LLM_ROUTER_LOG_FILENAME``)."""
    env_snapshot = {
        "LLM_ROUTER_LOG_FILENAME": str(tmp_path / "app.log"),
        "LLM_ROUTER_SERVER_PORT": "8080",
    }
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "server": "gunicorn",
            "log_file": str(tmp_path / "srv.log"),
            "env": env_snapshot,
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 0
        out = capsys.readouterr().out
        assert "Log" in out
        assert str(tmp_path / "app.log") in out
    finally:
        _kill(pid)


def test_status_log_row_prefers_recorded_app_log(pid_file, tmp_path, capsys):
    """``Log`` must show the absolute path stored in the run record, even
    when the env snapshot still carries only the bare file name."""
    app_log = tmp_path / "launch-dir" / "llm-router.log"
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "server": "gunicorn",
            "log_file": str(tmp_path / "srv.log"),
            "app_log_file": str(app_log),
            "env": {"LLM_ROUTER_LOG_FILENAME": "llm-router.log"},
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 0
        out = capsys.readouterr().out
        assert str(app_log) in out
    finally:
        _kill(pid)


def test_status_models_config_row_shows_recorded_absolute_path(
    pid_file, tmp_path, capsys
):
    """``Models config`` must show the absolute path stored in the run record,
    even when the env snapshot still carries only the relative name."""
    rel = "resources/configs/models-config.json"
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "server": "gunicorn",
            "models_config": str(Path.cwd() / rel),
            "env": {"LLM_ROUTER_MODELS_CONFIG": rel},
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 0
        out = capsys.readouterr().out
        assert "Models config" in out
        assert str(Path.cwd() / rel) in out
    finally:
        _kill(pid)


def test_status_falls_back_to_env_overrides_for_old_records(
    pid_file, tmp_path, capsys
):
    # Records written before the ``env`` field only carry ``env_overrides``.
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "started_at": "2026-01-01T00:00:00",
            "server": "gunicorn",
            "command": ["python3", "-m", "llm_router_api.rest_api"],
            "log_file": str(tmp_path / "srv.log"),
            "env_overrides": {"LLM_ROUTER_MODELS_CONFIG": "/tmp/custom.json"},
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert (
            ServerCommand.run(["status", "--pid-file", str(pid_file), "--show-env"])
            == 0
        )
        out = capsys.readouterr().out
        assert "Environment" in out
        assert "LLM_ROUTER_MODELS_CONFIG" in out
        assert "/tmp/custom.json" in out
    finally:
        _kill(pid)


def test_stop_removes_run_record(pid_file, tmp_path):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    run_file = server_module.run_file_for(pid_file)
    server_module.write_run_file(run_file, {"command": ["x"]})
    assert run_file.exists()

    try:
        assert ServerCommand.run(["stop", "--pid-file", str(pid_file)]) == 0
    finally:
        if pid_alive(pid):  # pragma: no cover - safety net
            _kill(pid)
    assert not run_file.exists()


def test_log_help_lists_flags(capsys):
    assert ServerCommand.run(["log", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in ("--log-file", "--lines", "--no-follow", "--color", "--pid-file"):
        assert flag in out


# ---- log (tail -f, colored) -----------------------------------------------


def test_colorize_line_wraps_known_levels():
    out = colorize_line("2026-01-01 INFO app: ok", "always")
    assert out.startswith("\033[32m") and out.endswith("\033[0m")
    assert colorize_line("2026-01-01 DEBUG app: d", "always").startswith("\033[36m")
    assert colorize_line("2026-01-01 WARNING app: w", "always").startswith(
        "\033[33m"
    )
    assert colorize_line("2026-01-01 WARN app: w", "always").startswith("\033[33m")
    assert colorize_line("2026-01-01 ERROR app: boom", "always").startswith(
        "\033[31m"
    )
    assert colorize_line("2026-01-01 CRITICAL app: dead", "always").startswith(
        "\033[1;31m"
    )


def test_colorize_line_untouched_cases():
    plain = "2026-01-01 12:00:00 app started"
    assert colorize_line(plain, "always") == plain
    assert (
        colorize_line("2026-01-01 ERROR app: boom", "never")
        == "2026-01-01 ERROR app: boom"
    )


def test_tail_lines_returns_last_n():
    import io

    fh = io.StringIO("\n".join(f"line {i}" for i in range(10)))
    assert [l.rstrip("\n") for l in tail_lines(fh, 3)] == [
        "line 7",
        "line 8",
        "line 9",
    ]
    fh = io.StringIO("a\nb\n")
    assert tail_lines(fh, 0) == []


def test_log_tail_no_follow_shows_last_lines(tmp_path, capsys):
    log = tmp_path / "server.log"
    log.write_text(
        "\n".join(f"2026-01-01 INFO app: line {i}" for i in range(10)) + "\n",
        encoding="utf-8",
    )
    rc = ServerCommand.run(
        [
            "log",
            "--log-file",
            str(log),
            "--lines",
            "3",
            "--no-follow",
            "--color",
            "never",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "2026-01-01 INFO app: line 7",
        "2026-01-01 INFO app: line 8",
        "2026-01-01 INFO app: line 9",
    ]


def test_log_color_always_colorizes_levels(tmp_path, capsys):
    log = tmp_path / "server.log"
    log.write_text("2026-01-01 ERROR app: boom\n", encoding="utf-8")
    rc = ServerCommand.run(
        [
            "log",
            "--log-file",
            str(log),
            "--lines",
            "1",
            "--no-follow",
            "--color",
            "always",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert out.startswith("\033[31m")
    assert out.rstrip("\n").endswith("\033[0m")


def test_log_lines_zero_prints_nothing(tmp_path, capsys):
    log = tmp_path / "server.log"
    log.write_text("2026-01-01 INFO app: x\n", encoding="utf-8")
    rc = ServerCommand.run(
        ["log", "--log-file", str(log), "--lines", "0", "--no-follow"]
    )
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_log_missing_file_fails(tmp_path, capsys):
    rc = ServerCommand.run(["log", "--log-file", str(tmp_path / "nope.log")])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not found" in err
    assert "server start" in err


def test_log_defaults_to_app_log_from_run_record(pid_file, tmp_path, capsys):
    """Without --log-file, the app log (LLM_ROUTER_LOG_FILENAME, recorded at
    start) is followed by default."""
    app_log = tmp_path / "launch-dir" / "llm-router.log"
    app_log.parent.mkdir(parents=True, exist_ok=True)
    app_log.write_text(
        "2026-01-01 INFO app: application line 1\n"
        "2026-01-01 INFO app: application line 2\n",
        encoding="utf-8",
    )
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "log_file": str(tmp_path / "srv.log"),
            "app_log_file": str(app_log),
        },
    )
    rc = ServerCommand.run(
        [
            "log",
            "--pid-file",
            str(pid_file),
            "--lines",
            "2",
            "--no-follow",
            "--color",
            "never",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "application line 1" in out
    assert "application line 2" in out


def test_log_resolves_env_log_filename_when_no_record(
    pid_file, tmp_path, monkeypatch, capsys
):
    """No run record -> fall back to the shell's LLM_ROUTER_LOG_FILENAME,
    anchored to the CWD for bare names."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_ROUTER_LOG_FILENAME", "env-app.log")
    rc = ServerCommand.run(
        [
            "log",
            "--pid-file",
            str(pid_file),
            "--lines",
            "1",
            "--no-follow",
        ]
    )
    assert rc == 1  # the resolved file does not exist
    err = capsys.readouterr().err
    assert str(tmp_path / "env-app.log") in err


def test_log_explicit_log_file_overrides_record(pid_file, tmp_path, capsys):
    explicit = tmp_path / "console.log"
    explicit.write_text("2026-01-01 INFO console: hello\n", encoding="utf-8")
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {"app_log_file": str(tmp_path / "app.log")},
    )
    rc = ServerCommand.run(
        [
            "log",
            "--log-file",
            str(explicit),
            "--pid-file",
            str(pid_file),
            "--lines",
            "1",
            "--no-follow",
        ]
    )
    assert rc == 0
    assert "hello" in capsys.readouterr().out


# ---- start: "already running" guard ----------------------------------------


def test_start_refuses_when_server_already_running(pid_file, tmp_path, capsys):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert main(["server", "start", "--pid-file", str(pid_file)]) == 1
        err = capsys.readouterr().err
        assert "already running" in err
        assert "server stop" in err
    finally:
        _kill(pid)


# ---- status: colored card rendering ----------------------------------------


def test_status_color_always_emits_ansi(pid_file, tmp_path, capsys):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    try:
        assert (
            ServerCommand.run(
                ["status", "--pid-file", str(pid_file), "--color", "always"]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "\033[1;32m" in out  # bold green "All good" header
        assert "\033[32m" in out  # green status dot
        assert "\033[0m" in out  # reset
    finally:
        _kill(pid)


def test_status_color_never_has_no_ansi(pid_file, tmp_path, capsys):
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    try:
        assert (
            ServerCommand.run(
                ["status", "--pid-file", str(pid_file), "--color", "never"]
            )
            == 0
        )
        out = capsys.readouterr().out
        assert "\033[" not in out
        assert "All good" in out
    finally:
        _kill(pid)


def test_status_down_state_color_always(pid_file, capsys):
    # No live PID -> red "Not running" card, still colorized on demand.
    assert (
        ServerCommand.run(
            ["status", "--pid-file", str(pid_file), "--color", "always"]
        )
        == 1
    )
    out = capsys.readouterr().out
    assert "not running" in out.lower()
    assert "\033[1;31m" in out  # bold red header
    assert "\033[31m" in out  # red status dot


def test_status_masks_sensitive_env(pid_file, tmp_path, capsys):
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "log_file": str(tmp_path / "srv.log"),
            "env": {
                "LLM_ROUTER_REDIS_PASSWORD": "hunter2-secret",
                "LLM_ROUTER_AUTH_VAULT_SECRET_ID": "vault-secret",
                "LLM_ROUTER_BALANCE_STRATEGY": "weighted",
            },
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    try:
        assert (
            ServerCommand.run(["status", "--pid-file", str(pid_file), "--show-env"])
            == 0
        )
        out = capsys.readouterr().out
        # Non-secret value is shown verbatim.
        assert "weighted" in out
        # Secret values are masked, never leaked.
        assert "hunter2-secret" not in out
        assert "vault-secret" not in out
        # The sensitive keys are present but their values are the mask token.
        assert "LLM_ROUTER_REDIS_PASSWORD" in out
        line = next(l for l in out.splitlines() if "LLM_ROUTER_REDIS_PASSWORD" in l)
        assert "****" in line
    finally:
        _kill(pid)


def test_status_env_hidden_by_default_shown_with_flag(pid_file, tmp_path, capsys):
    server_module.write_run_file(
        server_module.run_file_for(pid_file),
        {
            "log_file": str(tmp_path / "srv.log"),
            "server": "gunicorn",
            # ``LLM_ROUTER_LOG_LEVEL`` is *only* in the Environment section;
            # ``LLM_ROUTER_MODELS_CONFIG`` is also a first-class Details field.
            "env": {
                "LLM_ROUTER_MODELS_CONFIG": "/tmp/custom.json",
                "LLM_ROUTER_LOG_LEVEL": "TRACE",
            },
        },
    )
    pid = _spawn_detached(["sleep", "300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)
    try:
        # Default: the Environment section is hidden, Details is kept.
        assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 0
        out = capsys.readouterr().out
        assert "Details" in out
        assert "Environment" not in out
        assert "Models config" in out  # first-class Details field still shown
        assert "/tmp/custom.json" in out
        assert "TRACE" not in out  # Environment-only key is hidden

        # Opt-in: --show-env reveals the section again.
        assert (
            ServerCommand.run(["status", "--pid-file", str(pid_file), "--show-env"])
            == 0
        )
        out = capsys.readouterr().out
        assert "Environment (2)" in out
        assert "LLM_ROUTER_LOG_LEVEL" in out
        assert "TRACE" in out
    finally:
        _kill(pid)


# ---- status: rendering helpers (unit) --------------------------------------


def test_is_sensitive_matches_credentials_only():
    assert _is_sensitive("LLM_ROUTER_REDIS_PASSWORD")
    assert _is_sensitive("LLM_ROUTER_AUTH_VAULT_SECRET_ID")
    assert (
        _is_sensitive("LLM_ROUTER_AUTH_VAULT_ROLE_ID") is False
    )  # not a secret name
    assert _is_sensitive("LLM_ROUTER_API_KEY")
    assert _is_sensitive("LLM_ROUTER_BALANCE_STRATEGY") is False
    # Key-prefix/length config is NOT a credential.
    assert _is_sensitive("LLM_ROUTER_AUTH_KEY_PREFIX") is False
    assert _is_sensitive("LLM_ROUTER_AUTH_KEY_LENGTH") is False


def test_paint_toggles_ansi():
    assert _paint(False, "32", "hi") == "hi"
    assert _paint(True, "32", "hi") == "\033[32mhi\033[0m"


def test_resolve_color_modes(monkeypatch):
    assert _resolve_color("always") is True
    assert _resolve_color("never") is False
    monkeypatch.setattr(server_module.sys.stdout, "isatty", lambda: True)
    assert _resolve_color("auto") is True
    monkeypatch.setattr(server_module.sys.stdout, "isatty", lambda: False)
    assert _resolve_color("auto") is False
