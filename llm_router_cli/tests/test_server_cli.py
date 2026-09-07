"""
Tests for the ``llm-router server`` subcommand (run/stop/reload lifecycle).

Real server startups are avoided; ``stop``/``reload`` are exercised against
dummy *detached* processes (double-forked so they are not children of the
test process and thus never linger as zombies), and ``run`` is tested
through its "already running" guard. PID-file helpers and the
environment-defaults helper are tested directly.
"""

from __future__ import annotations

import os
import signal
import time

from pathlib import Path

import pytest

from llm_router_cli.cli import main
from llm_router_cli.cli.commands import server as server_module
from llm_router_cli.cli.commands.server import (
    DEFAULT_ENV,
    ServerCommand,
    apply_default_env,
    colorize_line,
    get_alive_pid,
    pid_alive,
    read_pid_file,
    remove_pid_file,
    tail_lines,
    write_pid_file,
)


# ---- fixtures / helpers ----------------------------------------------------


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


def _spawn_dead_pid() -> int:
    """Fork a child that exits immediately; return its (now dead) PID."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child exits right away
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


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
    ):
        assert flag in out


def test_stop_help_lists_flags(capsys):
    assert ServerCommand.run(["stop", "--help"]) == 0
    out = capsys.readouterr().out
    assert "--force" in out
    assert "--pid-file" in out


def test_invalid_server_choice_rejected(capsys):
    assert ServerCommand.run(["start", "--server", "uwsgi"]) == 2
    assert "invalid choice" in capsys.readouterr().err


def test_dispatch_routes_each_action(monkeypatch):
    calls = []
    for name in ("_start", "_stop", "_reload", "_status"):
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
    assert calls == ["_start", "_stop", "_reload", "_status"]


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


def test_invalid_lb_strategy_rejected(capsys):
    assert ServerCommand.run(["start", "--lb-strategy", "bogus"]) == 2
    assert "invalid choice" in capsys.readouterr().err


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
    assert ServerCommand.build_env_overrides(args) == {"LLM_ROUTER_AUTH_ENABLED": "false"}


def test_start_applies_overrides_beating_shell_env(monkeypatch, tmp_path, capsys):
    captured = {}

    def fake_call(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = dict(os.environ)
        return 0

    monkeypatch.setattr(server_module.subprocess, "call", fake_call)
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
    pid = _spawn_detached(["bash", "-c", "trap '' TERM; sleep 300"], tmp_path / "d.pid")
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


# ---- reload ---------------------------------------------------------------


def test_reload_sends_sighup_but_process_survives(pid_file, tmp_path, capsys):
    # HUP-tolerant dummy stands in for the Gunicorn master.
    pid = _spawn_detached(["bash", "-c", "trap '' HUP; sleep 300"], tmp_path / "d.pid")
    write_pid_file(pid_file, pid)

    try:
        assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 0
        out = capsys.readouterr().out
        assert "SIGHUP" in out
        assert str(pid) in out
        assert pid_alive(pid) is True
    finally:
        _kill(pid)


def test_reload_missing_pid_file(pid_file, capsys):
    assert ServerCommand.run(["reload", "--pid-file", str(pid_file)]) == 1
    assert "No running server found" in capsys.readouterr().err


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
    assert "NOT running" in capsys.readouterr().out


def test_status_cleans_stale_pid_file(pid_file, capsys):
    write_pid_file(pid_file, _spawn_dead_pid())
    assert ServerCommand.run(["status", "--pid-file", str(pid_file)]) == 1
    assert not pid_file.exists()
    assert "NOT running" in capsys.readouterr().out


def test_log_help_lists_flags(capsys):
    assert ServerCommand.run(["log", "--help"]) == 0
    out = capsys.readouterr().out
    for flag in ("--log-file", "--lines", "--no-follow", "--color"):
        assert flag in out


# ---- log (tail -f, colored) -----------------------------------------------


def test_colorize_line_wraps_known_levels():
    out = colorize_line("2026-01-01 INFO app: ok", "always")
    assert out.startswith("\033[32m") and out.endswith("\033[0m")
    assert colorize_line("2026-01-01 DEBUG app: d", "always").startswith("\033[36m")
    assert colorize_line("2026-01-01 WARNING app: w", "always").startswith("\033[33m")
    assert colorize_line("2026-01-01 WARN app: w", "always").startswith("\033[33m")
    assert colorize_line("2026-01-01 ERROR app: boom", "always").startswith("\033[31m")
    assert colorize_line("2026-01-01 CRITICAL app: dead", "always").startswith("\033[1;31m")


def test_colorize_line_untouched_cases():
    plain = "2026-01-01 12:00:00 app started"
    assert colorize_line(plain, "always") == plain
    assert colorize_line("2026-01-01 ERROR app: boom", "never") == "2026-01-01 ERROR app: boom"


def test_tail_lines_returns_last_n():
    import io

    fh = io.StringIO("\n".join(f"line {i}" for i in range(10)))
    assert [l.rstrip("\n") for l in tail_lines(fh, 3)] == ["line 7", "line 8", "line 9"]
    fh = io.StringIO("a\nb\n")
    assert tail_lines(fh, 0) == []


def test_log_tail_no_follow_shows_last_lines(tmp_path, capsys):
    log = tmp_path / "server.log"
    log.write_text(
        "\n".join(f"2026-01-01 INFO app: line {i}" for i in range(10)) + "\n",
        encoding="utf-8",
    )
    rc = ServerCommand.run(
        ["log", "--log-file", str(log), "--lines", "3", "--no-follow", "--color", "never"]
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
        ["log", "--log-file", str(log), "--lines", "1", "--no-follow", "--color", "always"]
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
