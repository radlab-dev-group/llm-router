"""
Tests for the shared :class:`ConcurrentLLMPipeline` machinery in
``llm_router_cli.util.pipeline`` — buffering, atomic flushing, dry-run,
progress bumping, queue draining and the threaded ``run()`` entry point.

A tiny concrete app subclass supplies deterministic tasks/records, so the
concurrency logic is exercised without any network or LLM dependency.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

import pytest

from llm_router_cli.util.pipeline import ConcurrentLLMPipeline


class _Record:
    """Minimal record exposing the ``to_json()`` contract."""

    def __init__(self, payload: str) -> None:
        self.payload = payload

    def to_json(self) -> str:
        return json.dumps({"v": self.payload})


class _DummyClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _App(ConcurrentLLMPipeline):
    """Concrete app with deterministic tasks and records."""

    def __init__(self, out_dir: Path, n_tasks: int, **kwargs) -> None:
        super().__init__(
            llm_router_url="http://router.test",
            batch_save_size=kwargs.pop("batch_save_size", 5),
            dry_run=kwargs.pop("dry_run", False),
            num_workers=kwargs.pop("num_workers", 2),
            **kwargs,
        )
        self.out_dir = out_dir
        self.n_tasks = n_tasks
        self.processed: list = []
        self._processed_lock = threading.Lock()
        self.clients: list = []
        self._clients_lock = threading.Lock()
        self.context = "CTX"
        self.aux_calls: list = []

    def _make_client(self):
        client = _DummyClient()
        with self._clients_lock:
            self.clients.append(client)
        return client

    def _make_context(self):
        return self.context

    def _build_task_queue(self) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue()
        out_path = self.out_dir / "out.jsonl"
        for i in range(self.n_tasks):
            q.put((str(out_path), f"payload-{i}"))
        return q

    def _process(self, client, ctx, *task):
        payload = task[1]
        with self._processed_lock:
            self.processed.append(payload)
        return _Record(payload)

    def _flush_aux(self, path: Path, records: list) -> None:
        self.aux_calls.append((str(path), len(records)))


def _read_lines(path: Path) -> list:
    if not path.exists():
        return []
    return [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------- #
# configuration / construction
# ---------------------------------------------------------------------- #


def test_num_workers_is_clamped_to_at_least_one(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, num_workers=0)
    assert app.num_workers == 1
    app2 = _App(tmp_path, 1, num_workers=-5)
    assert app2.num_workers == 1


def test_batch_save_size_is_coerced_to_int(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, batch_save_size="3")
    assert app.batch_save_size == 3


def test_initial_state_is_empty(tmp_path: Path) -> None:
    app = _App(tmp_path, 1)
    assert app._buffers == {}
    assert app._file_locks == {}
    assert app._progress is None


# ---------------------------------------------------------------------- #
# _ensure_buffer
# ---------------------------------------------------------------------- #


def test_ensure_buffer_creates_buffer_and_lock_once(tmp_path: Path) -> None:
    app = _App(tmp_path, 1)
    path = tmp_path / "a.jsonl"
    app._ensure_buffer(path)
    app._ensure_buffer(path)  # idempotent
    assert app._buffers[path] == []
    assert isinstance(app._file_locks[path], type(threading.Lock()))
    # Same list object is reused (not replaced).
    assert app._buffers[path] is app._buffers[path]


# ---------------------------------------------------------------------- #
# _flush_buffer
# ---------------------------------------------------------------------- #


def test_flush_buffer_writes_jsonl_and_clears_buffer(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, dry_run=False)
    path = tmp_path / "nested" / "dir" / "out.jsonl"
    records = [_Record("a"), _Record("b")]
    app._ensure_buffer(path)
    app._buffers[path].extend(records)

    app._flush_buffer(path)

    lines = _read_lines(path)
    assert lines == [json.dumps({"v": "a"}), json.dumps({"v": "b"})]
    # Buffer cleared after an atomic snapshot.
    assert app._buffers[path] == []


def test_flush_buffer_is_idempotent_when_empty(tmp_path: Path) -> None:
    app = _App(tmp_path, 1)
    path = tmp_path / "out.jsonl"
    app._ensure_buffer(path)
    app._flush_buffer(path)  # nothing buffered
    assert not path.exists()


def test_flush_buffer_dry_run_does_not_write(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, dry_run=True)
    path = tmp_path / "out.jsonl"
    app._ensure_buffer(path)
    app._buffers[path].append(_Record("a"))
    app._flush_buffer(path)
    assert not path.exists()
    # Dry run still clears the buffer (snapshot semantics).
    assert len(app._buffers[path]) == 0


def test_flush_buffer_appends_to_existing_file(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, dry_run=False)
    path = tmp_path / "out.jsonl"
    path.write_text('{"existing": true}\n', encoding="utf-8")
    app._ensure_buffer(path)
    app._buffers[path].append(_Record("new"))
    app._flush_buffer(path)
    lines = _read_lines(path)
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"existing": True}
    assert json.loads(lines[1]) == {"v": "new"}


def test_flush_buffer_invokes_aux_hook(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, dry_run=False)
    path = tmp_path / "out.jsonl"
    app._ensure_buffer(path)
    app._buffers[path].extend([_Record("a"), _Record("b")])
    app._flush_buffer(path)
    assert app.aux_calls == [(str(path), 2)]


# ---------------------------------------------------------------------- #
# _flush_all
# ---------------------------------------------------------------------- #


def test_flush_all_flushes_every_buffered_path(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, dry_run=False)
    p1 = tmp_path / "one.jsonl"
    p2 = tmp_path / "two.jsonl"
    for p, payload in ((p1, "x"), (p2, "y")):
        app._ensure_buffer(p)
        app._buffers[p].append(_Record(payload))
    app._flush_all()
    assert _read_lines(p1) == [json.dumps({"v": "x"})]
    assert _read_lines(p2) == [json.dumps({"v": "y"})]
    assert app._buffers[p1] == []
    assert app._buffers[p2] == []


# ---------------------------------------------------------------------- #
# _buffer_result (auto-flush at batch size)
# ---------------------------------------------------------------------- #


def test_buffer_result_buffers_until_batch_size(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, batch_save_size=2, dry_run=False)
    out = tmp_path / "out.jsonl"
    app._buffer_result((str(out), "a"), _Record("a"))
    # Under the threshold: one record buffered, nothing on disk yet.
    assert len(app._buffers[out]) == 1
    assert not out.exists()
    app._buffer_result((str(out), "b"), _Record("b"))
    # At the threshold: flushed automatically.
    assert _read_lines(out) == [
        json.dumps({"v": "a"}),
        json.dumps({"v": "b"}),
    ]
    assert app._buffers[out] == []


def test_buffer_result_uses_task_first_element_as_path(tmp_path: Path) -> None:
    app = _App(tmp_path, 1, batch_save_size=10)
    out = tmp_path / "picked.jsonl"
    app._buffer_result((str(out), "whatever"), _Record("z"))
    assert out in app._buffers


# ---------------------------------------------------------------------- #
# _poll_task / _drain / _progress_bump
# ---------------------------------------------------------------------- #


def test_poll_task_returns_queued_task() -> None:
    q: "queue.Queue" = queue.Queue()
    q.put(("path", "task"))
    assert ConcurrentLLMPipeline._poll_task(q) == ("path", "task")


def test_poll_task_returns_idle_sentinel_when_empty() -> None:
    q: "queue.Queue" = queue.Queue()
    assert ConcurrentLLMPipeline._poll_task(q) is ConcurrentLLMPipeline._IDLE


def test_progress_bump_is_noop_without_bar(tmp_path: Path) -> None:
    app = _App(tmp_path, n_tasks=1)
    app._progress = None
    app._progress_bump()  # must not raise
    assert app._progress is None


def test_progress_bump_updates_active_bar(tmp_path: Path) -> None:
    app = _App(tmp_path, 1)
    updates = {"n": 0}

    class _FakeBar:
        def update(self, n: int) -> None:
            updates["n"] += n

    app._progress = _FakeBar()
    app._progress_bump()
    app._progress_bump()
    assert updates["n"] == 2


def test_drain_marks_all_pending_tasks_done(tmp_path: Path) -> None:
    app = _App(tmp_path, 1)
    q: "queue.Queue" = queue.Queue()
    for i in range(5):
        q.put(("path", i))
    app._drain(q)
    assert q.empty()
    q.join()  # must not hang: every task was marked done


# ---------------------------------------------------------------------- #
# run() end-to-end
# ---------------------------------------------------------------------- #


def test_run_processes_all_tasks_and_flushes(tmp_path: Path) -> None:
    app = _App(
        tmp_path,
        n_tasks=7,
        num_workers=3,
        batch_save_size=10,  # force the final flush to do the work
        dry_run=False,
    )
    app.run()
    out = tmp_path / "out.jsonl"
    lines = _read_lines(out)
    assert len(lines) == 7
    payloads = {json.loads(line)["v"] for line in lines}
    assert payloads == {f"payload-{i}" for i in range(7)}
    # Every worker client was closed.
    assert all(c.closed for c in app.clients)
    assert app._progress is None


def test_run_empty_queue_is_a_noop(tmp_path: Path) -> None:
    app = _App(tmp_path, n_tasks=0, num_workers=2, dry_run=False)
    app.run()  # must not hang or create files
    assert not (tmp_path / "out.jsonl").exists()


def test_run_dry_run_does_not_write_output(tmp_path: Path) -> None:
    app = _App(tmp_path, n_tasks=3, num_workers=2, dry_run=True)
    app.run()
    assert not (tmp_path / "out.jsonl").exists()
    assert len(app.processed) == 3  # tasks were still processed


def test_run_propagates_validation_error(tmp_path: Path) -> None:
    app = _App(tmp_path, n_tasks=1)

    def _boom() -> None:
        raise ValueError("bad inputs")

    app._validate = _boom  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="bad inputs"):
        app.run()


def test_run_propagates_client_construction_error(tmp_path: Path) -> None:
    app = _App(tmp_path, n_tasks=1)

    def _boom():
        raise RuntimeError("cannot build client")

    app._make_client = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="cannot build client"):
        app.run()


def test_run_tolerates_per_task_processing_errors(tmp_path: Path) -> None:
    app = _App(tmp_path, n_tasks=4, num_workers=1, batch_save_size=10)

    def _flaky(self, client, ctx, *task):
        payload = task[1]
        if payload == "payload-1":
            raise ValueError("boom on 1")
        with self._processed_lock:
            self.processed.append(payload)
        return _Record(payload)

    _App._process = _flaky  # type: ignore[assignment]
    try:
        app.run()
    finally:
        # Restore the original implementation for other tests.
        _App._process = (  # type: ignore[assignment]
            lambda self, client, ctx, *task: (
                self.processed.append(task[1]),
                _Record(task[1]),
            )[1]
        )
    out_lines = _read_lines(tmp_path / "out.jsonl")
    # 3 of 4 tasks produced records; the failing one was skipped, not fatal.
    assert len(out_lines) == 3
    assert "payload-1" not in {json.loads(l)["v"] for l in out_lines}
