"""
Tests for the multi-instance support of ``llm-router server``.

Every instance keeps its own state tree under ``~/.llm-router/instances/<name>``
(``default`` keeps the historical flat layout). Covered here: name resolution
and validation, the per-instance ``config.env`` and its precedence, per-instance
metrics/log isolation, the start lock, port pre-flight checks, discovery plus
the ``list``/``rm-instance`` sub-commands and ``--all`` for ``stop``/``status``.

No real server is ever spawned: foreground starts run through a patched
``subprocess.Popen``, and ``stop``/``status`` use dummy double-forked
processes so they never linger as zombies.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import time

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from llm_router_cli.cli import main
from llm_router_cli.cli.commands import server as server_module
from llm_router_cli.cli.commands.server import (
    DEFAULT_INSTANCE,
    INSTANCE_ENV_VAR,
    ServerCommand,
    acquire_start_lock,
    discover_instances,
    get_alive_pid,
    log_file_for,
    parse_env_file,
    read_run_file,
    release_start_lock,
    resolve_instance,
    run_file_for,
    scaffold_config_env,
    write_pid_file,
    write_run_file,
)

# ---- fixtures / helpers ----------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_env():
    """``_apply_start_env`` mutates ``os.environ``; never leak that."""
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    """Point all instance state at *tmp_path* and start from a clean env."""
    monkeypatch.setattr(server_module, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(server_module, "DEFAULT_PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(server_module, "DEFAULT_LOG_FILE", tmp_path / "server.log")
    monkeypatch.delenv(INSTANCE_ENV_VAR, raising=False)
    monkeypatch.delenv("LLM_ROUTER_LOG_FILENAME", raising=False)
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


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
    """SIGKILL *pid* (if still alive) and wait until it is gone."""
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and server_module.pid_alive(pid):
        time.sleep(0.05)


def _spawn_dead_pid() -> int:
    """Fork a child that exits immediately; return its (now dead) PID."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child exits right away
        os._exit(0)
    os.waitpid(pid, 0)
    return pid


def _fake_spawn() -> Tuple[Dict[str, Any], List[List[str]]]:
    """Patch ``Popen`` so a start never launches anything.

    Returns ``(state, popen_calls)``; *state* holds the fake ``pid``, the
    environment captured at spawn time and the run record that would have been
    written (captured through :meth:`ServerCommand.build_run_record`, so it
    works for any instance, not only ``dev``).
    """
    state: Dict[str, Any] = {"pid": 4242, "env": {}, "record": None}
    calls: List[List[str]] = []

    class FakeProc:
        """Stand-in for the server child process."""

        def __init__(self, pid: int) -> None:
            self.pid = pid

        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kwargs):  # pragma: no cover - trivial stand-in
        calls.append(list(cmd))
        state["env"] = dict(os.environ)
        return FakeProc(state["pid"])

    original_build = ServerCommand.build_run_record.__func__

    def build_run_record(cls, *build_args, **build_kwargs):
        record = original_build(cls, *build_args, **build_kwargs)
        state["record"] = record
        return record

    server_module.subprocess.Popen = fake_popen  # type: ignore[method-assign]
    ServerCommand.build_run_record = classmethod(build_run_record)  # type: ignore[assignment]
    return state, calls


@pytest.fixture
def fake_spawn():
    """Provide the patched ``Popen`` and restore it afterwards."""
    original_popen = server_module.subprocess.Popen
    original_build = ServerCommand.build_run_record
    state, calls = _fake_spawn()
    try:
        yield state, calls
    finally:
        server_module.subprocess.Popen = original_popen  # type: ignore[method-assign]
        ServerCommand.build_run_record = original_build  # type: ignore[method-assign]


def _resolve(
    args: Optional[argparse.Namespace] = None,
) -> server_module.InstancePaths:
    """Resolve instance paths from *args* (``None`` → default/env selection)."""
    return resolve_instance(
        argparse.Namespace() if args is None else argparse.Namespace(**vars(args))
    )


def _instance(name: str) -> server_module.InstancePaths:
    """Resolve the instance called *name* against the patched state directory."""
    return _resolve(argparse.Namespace(instance=name))


def _write_record(target, **fields: Any) -> Dict[str, Any]:
    """Write a minimal run record for the *target* instance and return it."""
    record: Dict[str, Any] = {"server": "gunicorn"}
    record.update(fields)
    write_run_file(target.run_file, record)
    return record


# ---- instance resolution ---------------------------------------------------


def test_default_instance_keeps_the_legacy_layout(state_home):
    instance = _instance(DEFAULT_INSTANCE)

    assert instance.named is False
    assert instance.dir == state_home
    assert instance.pid_file == state_home / "server.pid"
    assert instance.run_file == state_home / "server.pid.run"
    assert instance.daemon_log == state_home / "server.log"
    assert instance.app_log is None
    assert instance.pid_file == server_module.DEFAULT_PID_FILE
    assert instance.daemon_log == server_module.DEFAULT_LOG_FILE


def test_named_instance_gets_its_own_state_tree(state_home):
    instance = _instance("dev")

    assert instance.named is True
    root = state_home / "instances" / "dev"
    assert instance.dir == root
    assert instance.pid_file == root / "server.pid"
    assert instance.run_file == root / "server.pid.run"
    assert instance.daemon_log == root / "server.log"
    assert instance.config_env == root / "config.env"
    assert instance.metrics_dir == root / "metrics" / "prometheus" / "multiproc"
    assert instance.app_log == root / "llm-router.log"
    assert instance.lock_file == root / "server.start.lock"


def test_env_variable_selects_the_instance(state_home, monkeypatch):
    monkeypatch.setenv(INSTANCE_ENV_VAR, "staging")

    assert _resolve().name == "staging"
    assert _resolve().dir == state_home / "instances" / "staging"


def test_cli_flag_beats_the_env_variable(state_home, monkeypatch):
    monkeypatch.setenv(INSTANCE_ENV_VAR, "staging")

    assert _resolve(argparse.Namespace(instance="dev")).name == "dev"


@pytest.mark.parametrize(
    "name",
    ["bad/name", "..", "../elsewhere", "with space", "x" * 65, ".hidden"],
)
def test_resolve_instance_rejects_unsafe_names(state_home, name):
    with pytest.raises(ValueError, match="invalid instance name"):
        resolve_instance(argparse.Namespace(instance=name))


def test_an_empty_instance_name_falls_back_to_default(state_home):
    assert _resolve(argparse.Namespace(instance="")).name == DEFAULT_INSTANCE


def test_start_rejects_an_invalid_instance_name(state_home, capsys):
    assert ServerCommand.run(["start", "-i", "bad/name"]) == 1

    assert "invalid instance name" in capsys.readouterr().err


def test_explicit_pid_file_wins_over_the_instance(state_home):
    instance = _instance("dev")
    explicit = state_home / "custom.pid"
    args = argparse.Namespace(pid_file=str(explicit))

    assert ServerCommand._pid_file_for(args, instance) == explicit
    assert (
        ServerCommand._pid_file_for(argparse.Namespace(pid_file=None), instance)
        == instance.pid_file
    )


# ---- config.env ------------------------------------------------------------


def test_parse_env_file_accepts_common_syntax(state_home):
    path = state_home / "config.env"
    path.write_text(
        "# a comment\n"
        "\n"
        "LLM_ROUTER_SERVER_PORT=8123\n"
        "  export LLM_ROUTER_SERVER_HOST=127.0.0.1  \n"
        'LLM_ROUTER_MODELS_CONFIG="/opt/models.json"\n'
        "LLM_ROUTER_PROMPTS_DIR=~/prompts\n"
        "LLM_ROUTER_LOG_LEVEL=\n",
        encoding="utf-8",
    )

    values = parse_env_file(path)

    assert values["LLM_ROUTER_SERVER_PORT"] == "8123"
    assert values["LLM_ROUTER_SERVER_HOST"] == "127.0.0.1"
    assert values["LLM_ROUTER_MODELS_CONFIG"] == "/opt/models.json"
    assert values["LLM_ROUTER_PROMPTS_DIR"] == (f"{os.path.expanduser('~')}/prompts")
    assert values["LLM_ROUTER_LOG_LEVEL"] == ""


def test_parse_env_file_of_a_missing_path_is_empty(state_home):
    assert parse_env_file(state_home / "nope.env") == {}


def test_parse_env_file_warns_about_unusable_lines(state_home, capsys):
    path = state_home / "config.env"
    path.write_text(
        "JUST_A_WORD\n" "SOME_OTHER_TOOL=1\n" "=novariable\n",
        encoding="utf-8",
    )

    assert parse_env_file(path) == {}

    err = capsys.readouterr().err
    assert err.count("Warning:") == 3
    assert "no '='" in err
    assert "SOME_OTHER_TOOL" in err


def test_scaffold_config_env_creates_once_and_never_overwrites(state_home):
    instance = _instance("dev")

    assert scaffold_config_env(instance.config_env, "dev") is True
    assert "LLM_ROUTER" in instance.config_env.read_text(encoding="utf-8")

    instance.config_env.write_text("# hand written\n", encoding="utf-8")
    assert scaffold_config_env(instance.config_env, "dev") is False
    assert instance.config_env.read_text(encoding="utf-8") == "# hand written\n"


# ---- precedence: CLI flag > config.env > shell env > defaults --------------


def test_config_env_beats_the_shell_environment(state_home, fake_spawn, monkeypatch):
    instance = _instance("dev")
    instance.ensure_dir()
    instance.config_env.write_text(
        "LLM_ROUTER_DEFAULT_EP_LANGUAGE=de\n", encoding="utf-8"
    )
    monkeypatch.setenv("LLM_ROUTER_DEFAULT_EP_LANGUAGE", "es")

    state, calls = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 0
    )

    assert state["env"]["LLM_ROUTER_DEFAULT_EP_LANGUAGE"] == "de"
    assert calls


def test_cli_flag_beats_config_env_and_shell(state_home, fake_spawn, monkeypatch):
    instance = _instance("dev")
    instance.ensure_dir()
    instance.config_env.write_text(
        "LLM_ROUTER_DEFAULT_EP_LANGUAGE=de\n", encoding="utf-8"
    )
    monkeypatch.setenv("LLM_ROUTER_DEFAULT_EP_LANGUAGE", "es")

    state, _ = fake_spawn
    assert (
        ServerCommand.run(
            [
                "start",
                "--foreground",
                "-i",
                "dev",
                "--no-port-check",
                "--default-lang",
                "en",
            ]
        )
        == 0
    )

    assert state["env"]["LLM_ROUTER_DEFAULT_EP_LANGUAGE"] == "en"


def test_builtin_defaults_only_fill_the_gaps(state_home, fake_spawn, monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_LOG_LEVEL", "DEBUG")

    state, _ = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 0
    )

    assert state["env"]["LLM_ROUTER_LOG_LEVEL"] == "DEBUG"
    assert state["env"]["LLM_ROUTER_SERVER_WORKERS_COUNT"] == "4"


# ---- per-instance isolation ------------------------------------------------


def test_named_instance_gets_its_own_metrics_dir_and_app_log(state_home, fake_spawn):
    instance = _instance("dev")

    state, _ = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 0
    )

    assert state["env"]["PROMETHEUS_MULTIPROC_DIR"] == str(instance.metrics_dir)
    assert instance.metrics_dir.is_dir()
    assert state["env"]["LLM_ROUTER_LOG_FILENAME"] == str(instance.app_log)

    record = state["record"]
    assert record is not None
    assert record["instance"] == "dev"
    assert record["log_file"] == str(instance.daemon_log)


def test_named_instance_keeps_an_explicit_shell_app_log(
    state_home, fake_spawn, monkeypatch
):
    monkeypatch.setenv("LLM_ROUTER_LOG_FILENAME", "custom-app.log")

    state, _ = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 0
    )

    assert state["env"]["LLM_ROUTER_LOG_FILENAME"] == "custom-app.log"


def test_named_instance_keeps_an_explicit_prometheus_dir(
    state_home, fake_spawn, monkeypatch
):
    shared = state_home / "shared-metrics"
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(shared))

    state, _ = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 0
    )

    assert state["env"]["PROMETHEUS_MULTIPROC_DIR"] == str(shared)


def test_default_instance_does_not_force_a_prometheus_dir(state_home, fake_spawn):
    state, _ = fake_spawn
    assert ServerCommand.run(["start", "--foreground", "--no-port-check"]) == 0

    assert "PROMETHEUS_MULTIPROC_DIR" not in state["env"]
    assert state["record"]["instance"] == DEFAULT_INSTANCE
    assert state["record"]["log_file"] == str(state_home / "server.log")


def test_log_file_for_precedence(state_home):
    named = _instance("dev")
    default = _instance(DEFAULT_INSTANCE)
    explicit = argparse.Namespace(log_file="/tmp/explicit.log")
    plain = argparse.Namespace(log_file=None)

    assert log_file_for(explicit, named, "shell.log") == Path("/tmp/explicit.log")
    # a named instance ignores the shell's application-log name ...
    assert log_file_for(plain, named, "shell.log") == named.daemon_log
    # ... while the legacy default instance still honors it
    assert log_file_for(plain, default, "shell.log") == Path.cwd() / "shell.log"
    assert log_file_for(plain, default, None) == state_home / "server.log"


# ---- port pre-flight -------------------------------------------------------


def test_start_refuses_a_port_used_by_another_instance(
    state_home, fake_spawn, capsys
):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    probe.listen(1)
    busy_port = probe.getsockname()[1]
    state, calls = fake_spawn
    try:
        assert (
            ServerCommand.run(
                [
                    "start",
                    "--foreground",
                    "-i",
                    "dev",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(busy_port),
                ]
            )
            == 1
        )
    finally:
        probe.close()

    err = capsys.readouterr().err
    assert "already in use" in err
    assert str(_instance("dev").config_env) in err
    assert calls == []
    assert not _instance("dev").pid_file.exists()


# ---- start lock ------------------------------------------------------------


def test_a_held_start_lock_blocks_a_concurrent_start(state_home, fake_spawn, capsys):
    instance = _instance("dev")
    instance.ensure_dir()
    instance.lock_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

    _, calls = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 1
    )

    assert "already in progress" in capsys.readouterr().err
    assert calls == []
    assert not instance.pid_file.exists()


def test_a_stale_start_lock_is_broken(state_home, fake_spawn):
    instance = _instance("dev")
    instance.ensure_dir()
    instance.lock_file.write_text("999999\n", encoding="utf-8")
    stale = time.time() - 120
    os.utime(instance.lock_file, (stale, stale))

    _, calls = fake_spawn
    assert (
        ServerCommand.run(["start", "--foreground", "-i", "dev", "--no-port-check"])
        == 0
    )

    assert len(calls) == 1
    assert not instance.lock_file.exists()


def test_acquire_start_lock_is_exclusive(state_home):
    instance = _instance("dev")

    lock = acquire_start_lock(instance)
    try:
        assert lock is not None
        assert lock == instance.lock_file
        assert acquire_start_lock(instance) is None
    finally:
        release_start_lock(lock)

    assert not instance.lock_file.exists()
    reacquired = acquire_start_lock(instance)
    release_start_lock(reacquired)
    assert reacquired is not None


# ---- discovery -------------------------------------------------------------


def test_discover_instances_is_empty_without_state(state_home):
    assert discover_instances() == []


def test_the_default_instance_is_only_discovered_with_state(state_home):
    default = _instance(DEFAULT_INSTANCE)

    assert [item.name for item in discover_instances()] == []

    write_pid_file(default.pid_file, os.getpid())
    assert [item.name for item in discover_instances()] == [DEFAULT_INSTANCE]


def test_a_named_instance_survives_on_its_config_env_alone(state_home):
    instance = _instance("dev")
    scaffold_config_env(instance.config_env, instance.name)

    assert [item.name for item in discover_instances()] == ["dev"]


def test_discover_instances_skips_junk_and_sorts_by_name(state_home):
    for name in ("prod", "dev"):
        instance = _instance(name)
        instance.ensure_dir()
        scaffold_config_env(instance.config_env, name)
    (state_home / "instances" / "bad name!").mkdir(parents=True)

    assert [item.name for item in discover_instances()] == ["dev", "prod"]


def test_run_record_round_trip(state_home):
    instance = _instance("dev")
    _write_record(
        instance,
        instance="dev",
        started_at="2026-01-01T00:00:00+0200",
        env={"LLM_ROUTER_SERVER_PORT": "8091"},
    )

    assert run_file_for(instance.pid_file) == instance.run_file
    record = read_run_file(instance.run_file)
    assert record is not None
    assert record["instance"] == "dev"
    assert read_run_file(instance.dir / "missing.json") is None


# ---- list ------------------------------------------------------------------


def test_list_without_instances_says_so(state_home, capsys):
    assert ServerCommand.run(["list", "--color", "never"]) == 0
    assert "no instances found" in capsys.readouterr().out


def test_list_reports_a_stopped_instance(state_home, capsys):
    instance = _instance("dev")
    instance.ensure_dir()
    _write_record(
        instance,
        env={"LLM_ROUTER_SERVER_PORT": "8091"},
        started_at="2026-01-01T00:00:00+0200",
    )

    assert ServerCommand.run(["list", "--color", "never"]) == 0

    out = capsys.readouterr().out
    assert "NAME" in out and "STATUS" in out and "PORT" in out
    assert "dev" in out
    assert "stopped" in out
    assert "8091" in out
    assert "gunicorn" in out
    assert "2026-01-01T00:00:00+0200" in out
    assert "-" in out  # the missing PID becomes a placeholder


def test_list_json_is_machine_readable(state_home, capsys):
    instance = _instance("dev")
    instance.ensure_dir()
    _write_record(instance, env={"LLM_ROUTER_SERVER_PORT": "8091"})

    assert ServerCommand.run(["list", "--json"]) == 0

    entries = json.loads(capsys.readouterr().out)
    assert len(entries) == 1
    entry = entries[0]
    assert entry["name"] == "dev"
    assert entry["status"] == "stopped"
    assert entry["pid"] is None
    assert entry["port"] == "8091"
    assert entry["pid_file"] == str(instance.pid_file)


def test_list_json_is_an_empty_array_without_instances(state_home, capsys):
    assert ServerCommand.run(["list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_list_is_reachable_through_the_top_level_cli(state_home, capsys):
    assert main(["server", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


# ---- stop / status --all ---------------------------------------------------


def test_stop_all_without_instances_fails(state_home, capsys):
    assert ServerCommand.run(["stop", "--all"]) == 1
    assert "No running server found" in capsys.readouterr().err


def test_stop_all_stops_live_instances_and_skips_stale_ones(state_home, capsys):
    dev = _instance("dev")
    staging = _instance("staging")
    pid_dir = state_home / "pids"
    pid_dir.mkdir()
    dev_pid = _spawn_detached(["sleep", "300"], pid_dir / "dev.pid")
    write_pid_file(dev.pid_file, dev_pid)
    _write_record(dev, instance="dev")
    write_pid_file(staging.pid_file, _spawn_dead_pid())

    try:
        assert ServerCommand.run(["stop", "--all"]) == 0
    finally:
        _kill(dev_pid)

    out = capsys.readouterr().out
    assert "stopping dev" in out
    assert "not running: staging" in out
    assert not dev.pid_file.exists()
    assert not dev.run_file.exists()
    assert not staging.pid_file.exists()
    assert not staging.run_file.exists()


def test_status_all_reports_every_instance(state_home, capsys):
    dev = _instance("dev")
    prod = _instance("prod")
    pid_dir = state_home / "pids"
    pid_dir.mkdir()
    dev_pid = _spawn_detached(["sleep", "300"], pid_dir / "dev.pid")
    prod_pid = _spawn_detached(["sleep", "300"], pid_dir / "prod.pid")
    for instance, pid in ((dev, dev_pid), (prod, prod_pid)):
        write_pid_file(instance.pid_file, pid)
        _write_record(instance, env={"LLM_ROUTER_SERVER_PORT": "8080"})

    try:
        assert ServerCommand.run(["status", "--all", "--color", "never"]) == 0
        out = capsys.readouterr().out
        assert "Instances (2)" in out
        assert out.count("● running") == 2

        _kill(prod_pid)
        assert ServerCommand.run(["status", "--all", "--color", "never"]) == 1
        out = capsys.readouterr().out
        assert "● stopped" in out and "● running" in out
    finally:
        _kill(dev_pid)
        _kill(prod_pid)


def test_status_all_without_instances_reports_and_fails(state_home, capsys):
    assert ServerCommand.run(["status", "--all", "--color", "never"]) == 1
    assert "No instances found." in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        ["stop", "--all", "-i", "dev"],
        ["status", "--all", "--pid-file", "custom.pid"],
    ],
)
def test_all_conflicts_with_a_single_target(argv, state_home, capsys):
    assert ServerCommand.run(argv) == 1
    assert "--all cannot be combined" in capsys.readouterr().err


# ---- rm-instance -----------------------------------------------------------


def test_rm_instance_removes_a_stopped_instance(state_home, capsys):
    instance = _instance("dev")
    instance.ensure_dir()
    _write_record(instance)

    assert ServerCommand.run(["rm-instance", "dev"]) == 0

    assert not instance.dir.exists()
    assert "Removed instance 'dev'" in capsys.readouterr().out


def test_rm_instance_refuses_a_running_instance(state_home, capsys):
    instance = _instance("dev")
    instance.ensure_dir()
    write_pid_file(instance.pid_file, os.getpid())

    assert ServerCommand.run(["rm-instance", "dev"]) == 1

    assert "is running (pid=" in capsys.readouterr().err
    assert instance.dir.is_dir()


def test_rm_instance_refuses_the_built_in_instance(state_home, capsys):
    assert ServerCommand.run(["rm-instance", DEFAULT_INSTANCE]) == 1
    assert "built-in instance" in capsys.readouterr().err


def test_rm_instance_rejects_an_unknown_instance(state_home, capsys):
    assert ServerCommand.run(["rm-instance", "ghost"]) == 1
    assert "no such instance: ghost" in capsys.readouterr().err


def test_rm_instance_rejects_an_unsafe_name(state_home, capsys):
    assert ServerCommand.run(["rm-instance", "bad/name"]) == 1
    assert "invalid instance name" in capsys.readouterr().err


# ---- two instances side by side -------------------------------------------


def test_two_instances_run_side_by_side(state_home, capsys):
    dev = _instance("dev")
    prod = _instance("prod")
    pid_dir = state_home / "pids"
    pid_dir.mkdir()
    dev_pid = _spawn_detached(["sleep", "300"], pid_dir / "dev.pid")
    prod_pid = _spawn_detached(["sleep", "300"], pid_dir / "prod.pid")
    for instance, pid, port in (
        (dev, dev_pid, "8081"),
        (prod, prod_pid, "8080"),
    ):
        instance.ensure_dir()
        write_pid_file(instance.pid_file, pid)
        _write_record(
            instance, instance=instance.name, env={"LLM_ROUTER_SERVER_PORT": port}
        )

    try:
        assert ServerCommand.run(["list", "--json"]) == 0
        entries = {
            entry["name"]: entry for entry in json.loads(capsys.readouterr().out)
        }
        assert entries["dev"]["status"] == "running"
        assert entries["dev"]["port"] == "8081"
        assert entries["prod"]["status"] == "running"
        assert entries["prod"]["port"] == "8080"
        assert entries["dev"]["pid"] == dev_pid

        assert ServerCommand.run(["stop", "--all"]) == 0
    finally:
        _kill(dev_pid)
        _kill(prod_pid)

    assert get_alive_pid(dev.pid_file) is None
    assert get_alive_pid(prod.pid_file) is None
    assert not dev.pid_file.exists()
    assert not prod.pid_file.exists()
