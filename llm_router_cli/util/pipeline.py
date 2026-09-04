"""
Shared concurrent pipeline for the GenAI ``util`` apps.

Both :class:`~llm_router_cli.util.genai_classifier.GenAIClassifierApp` and
:class:`~llm_router_cli.util.genai_data_augmentation.GenAIDataAugmentationApp`
share the same infrastructure:

* fan a batch of tasks out to a pool of worker threads, each owning its own
  :class:`llm_router_lib.client.LLMRouterClient`;
* collect the resulting records into a per‑file, thread‑safe buffer;
* flush the buffer to a primary JSONL file (plus an optional auxiliary file)
  every ``batch_save_size`` records and once more at the end;
* advance a single thread‑safe ``tqdm`` progress bar per processed task,
  so every run shows live progress regardless of worker count.

:class:`ConcurrentLLMPipeline` owns that machinery once.  Concrete apps only
supply the app‑specific pieces: input validation, task‑queue construction,
how to process a single task, and (optionally) how to render an auxiliary
file.  Every record produced by an app must expose a ``to_json() -> str``
method.

Concurrency notes
-----------------
* Buffers and their locks live behind a single ``_buffers_lock``; a flush
  takes an **atomic snapshot** of the buffer (and clears it) under that lock,
  so records appended by other workers are never lost or duplicated.
* Per‑file writes are serialized with a per‑path lock, keeping JSONL lines of
  concurrent flushes in a consistent order.
* If a worker thread dies unexpectedly, it drains the queue (marking the
  remaining tasks as done) before propagating, so ``run()`` can never hang on
  ``queue.join()``.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_router_lib.client import LLMRouterClient
from tqdm import tqdm

from ..log_utils import shorten

log = logging.getLogger(__name__)


class ConcurrentLLMPipeline:
    """Threaded, buffered JSONL pipeline shared by the GenAI ``util`` apps."""

    #: Sentinel returned by :meth:`_poll_task` when the task queue is idle.
    _IDLE = object()

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        *,
        llm_router_url: str,
        llm_router_token: Optional[str] = None,
        llm_router_timeout: int = 10,
        batch_save_size: int = 5,
        dry_run: bool = False,
        verbose: bool = False,
        num_workers: int = 2,
    ) -> None:
        self.llm_router_url = llm_router_url
        self.llm_router_token = llm_router_token
        self.llm_router_timeout = llm_router_timeout
        self.batch_save_size = int(batch_save_size)
        self.dry_run = dry_run
        self.verbose = verbose
        self.num_workers = max(1, int(num_workers))

        # Shared, thread‑safe buffering structures.
        self._buffers: Dict[Path, List[Any]] = {}
        self._file_locks: Dict[Path, threading.Lock] = {}
        self._buffers_lock = threading.Lock()

        #: Run‑wide progress bar; created in :meth:`run`, ``None`` outside it.
        self._progress: Optional[tqdm] = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Release shared resources (each worker owns its own client)."""

    # ------------------------------------------------------------------ #
    # Hooks implemented by concrete apps
    # ------------------------------------------------------------------ #
    def _make_client(self) -> LLMRouterClient:
        """Create the per‑worker HTTP client."""
        return LLMRouterClient(
            self.llm_router_url,
            token=self.llm_router_token,
            timeout=self.llm_router_timeout,
        )

    def _make_context(self) -> Any:
        """Build the per‑worker context handed to :meth:`_process`.

        Returns ``None`` by default; apps override to supply their context.
        """
        return None

    def _validate(self) -> None:
        """Validate inputs, raising ``ValueError`` on a fatal problem.

        No‑op by default; apps override to check their preconditions.
        """

    def _build_task_queue(self) -> queue.Queue[Any]:
        """Populate and return the task queue for the workers to consume."""
        raise NotImplementedError

    def _process(
        self, client: LLMRouterClient, ctx: Any, *task: Any
    ) -> Optional[Any]:
        """Process a single task and return a record, or ``None`` to skip it."""
        raise NotImplementedError

    def _flush_aux(self, path: Path, records: List[Any]) -> None:
        """Write an auxiliary file for *records* (none by default)."""

    def _progress_description(self) -> str:
        """Label shown on the run‑wide progress bar (apps may override)."""
        return "Processing"

    # ------------------------------------------------------------------ #
    # Shared machinery
    # ------------------------------------------------------------------ #
    def _ensure_buffer(self, path: Path) -> None:
        """Make sure a buffer/lock pair exists for *path*."""
        with self._buffers_lock:
            self._buffers.setdefault(path, [])
            self._file_locks.setdefault(path, threading.Lock())

    def _flush_buffer(self, path: Path) -> None:
        """Write the buffered records for *path* to disk (thread‑safe).

        The buffer snapshot is taken (and cleared) atomically under
        ``_buffers_lock``, so records appended by other workers in between
        are never lost; the actual write is serialized per file.
        """
        with self._buffers_lock:
            buffer = self._buffers.get(path, [])
            if not buffer:
                return
            records, buffer[:] = list(buffer), []
            lock = self._file_locks.setdefault(path, threading.Lock())

        if self.dry_run:
            log.debug(
                "Dry run: skipped flush of %d record(s) for %s",
                len(records),
                path.name,
            )
            return

        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(record.to_json() + "\n")
            self._flush_aux(path, records)
        log.debug("Flushed %d record(s) to %s", len(records), path.name)

    def _flush_all(self) -> None:
        """Flush every buffered file (final end‑of‑run flush)."""
        with self._buffers_lock:
            paths = list(self._buffers)
        for path in paths:
            self._flush_buffer(path)

    @staticmethod
    def _poll_task(task_queue: queue.Queue[Any]) -> Any:
        """Return the next task, or the :data:`_IDLE` sentinel when idle.

        A 1 s bounded wait lets workers exit promptly once the queue is
        drained, without spinning on ``get()``.
        """
        try:
            return task_queue.get(timeout=1)
        except queue.Empty:
            return ConcurrentLLMPipeline._IDLE

    def _buffer_result(self, task: Any, record: Any) -> None:
        """Append *record* to the task's output buffer, flushing if full."""
        output_path = Path(task[0])
        self._ensure_buffer(output_path)
        with self._buffers_lock:
            buf = self._buffers[output_path]
            buf.append(record)
            need_flush = len(buf) >= self.batch_save_size
        if need_flush:
            self._flush_buffer(output_path)

    # ------------------------------------------------------------------ #
    # Workers
    # ------------------------------------------------------------------ #
    def _process_loop(
        self,
        client: LLMRouterClient,
        ctx: Any,
        task_queue: queue.Queue[Any],
    ) -> None:
        """Consume tasks, process them and buffer the results."""
        while True:
            task = self._poll_task(task_queue)
            if task is self._IDLE:
                break
            started = time.perf_counter()
            try:
                record = self._process(client, ctx, *task)
                if record is not None:
                    self._buffer_result(task, record)
            except Exception as exc:  # keep the pool alive on a bad task
                log.exception(
                    "Failed to process task %s: %s", shorten(repr(task)), exc
                )
            finally:
                task_queue.task_done()
                self._progress_bump()
                log.debug(
                    "Task done in %.3fs: %s",
                    time.perf_counter() - started,
                    shorten(repr(task)),
                )

    def _progress_bump(self) -> None:
        """Advance the run‑wide progress bar (thread‑safe; no‑op when idle)."""
        if self._progress is not None:
            self._progress.update(1)

    def _drain(self, task_queue: queue.Queue[Any]) -> None:
        """Mark every pending task as done (so ``join()`` cannot hang)."""
        while not task_queue.empty():
            try:
                task_queue.get_nowait()
                task_queue.task_done()
                self._progress_bump()
            except queue.Empty:  # pragma: no cover - another worker got it
                break

    def _worker(self, task_queue: queue.Queue[Any]) -> None:
        """Thread target: own one client and process tasks until drained."""
        client = self._make_client()
        log.debug(
            "Worker %s ready (router: %s)",
            threading.current_thread().name,
            self.llm_router_url,
        )
        try:
            ctx: Any = self._make_context()  # base hook may return None
            self._process_loop(client, ctx, task_queue)
        except Exception:
            # A crashed worker must not leave tasks unprocessed — otherwise
            # ``task_queue.join()`` in :meth:`run` would hang forever.
            log.exception(
                "Worker crashed; draining %d pending task(s)", task_queue.qsize()
            )
            self._drain(task_queue)
            raise
        finally:
            client.close()

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Execute the pipeline: validate, build the queue, run workers, flush."""
        self._validate()
        # Build a client eagerly so construction errors surface synchronously
        # instead of inside (daemon) worker threads; close it right away —
        # each worker owns its own client.
        probe_client = self._make_client()
        probe_client.close()
        task_queue = self._build_task_queue()

        if task_queue.qsize():
            self._progress = tqdm(
                total=task_queue.qsize(),
                desc=self._progress_description(),
                unit="task",
            )
        try:
            threads = [
                threading.Thread(
                    target=self._worker,
                    args=(task_queue,),
                    name=f"llm-pipeline-worker-{index}",
                    daemon=True,
                )
                for index in range(self.num_workers)
            ]
            for thread in threads:
                thread.start()
            task_queue.join()
            for thread in threads:
                thread.join()

            self._flush_all()
        finally:
            if self._progress is not None:
                self._progress.close()
                self._progress = None
        log.info("Processing finished.")
