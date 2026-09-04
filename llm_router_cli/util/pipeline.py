"""
Shared concurrent pipeline for the GenAI ``util`` apps.

Both :class:`~llm_router_cli.util.genai_classifier.GenAIClassifierApp` and
:class:`~llm_router_cli.util.genai_data_augmentation.GenAIDataAugmentationApp`
share the same infrastructure:

* fan a batch of tasks out to a pool of worker threads, each owning its own
  :class:`llm_router_lib.client.LLMRouterClient`;
* collect the resulting records into a per‑file, thread‑safe buffer;
* flush the buffer to a primary JSONL file (plus an optional auxiliary file)
  every ``batch_save_size`` records and once more at the end.

:class:`ConcurrentLLMPipeline` owns that machinery once.  Concrete apps only
supply the app‑specific pieces: input validation, task‑queue construction,
how to process a single task, and (optionally) how to render an auxiliary file.
Every record produced by an app must expose a ``to_json() -> str`` method.
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_router_lib.client import LLMRouterClient

log = logging.getLogger(__name__)


class ConcurrentLLMPipeline:
    """Threaded, buffered JSONL pipeline shared by the GenAI ``util`` apps."""

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

        if verbose:
            log.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Release any shared resources (no‑op; each worker owns its client)."""
        return None

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
        """Build the per-worker context handed to :meth:`_process`.

        Returns ``None`` by default; apps override to supply their context.
        """
        return None

    def _validate(self) -> None:
        """Validate inputs, raising ``ValueError`` on a fatal problem.

        No-op by default; apps override to check their preconditions.
        """
        return None

    def _build_task_queue(self) -> "queue.Queue":
        """Populate and return the task queue for the workers to consume."""
        raise NotImplementedError

    def _process(
        self, client: LLMRouterClient, ctx: Any, *task: Any
    ) -> Optional[Any]:
        """Process a single task and return a record, or ``None`` to skip it."""
        raise NotImplementedError

    def _flush_aux(self, path: Path, records: List[Any]) -> None:
        """Write an auxiliary file for *records* (no auxiliary output by default)."""
        return None

    # ------------------------------------------------------------------ #
    # Shared machinery
    # ------------------------------------------------------------------ #
    def _ensure_buffer(self, path: Path) -> None:
        """Make sure a buffer/lock pair exists for *path*."""
        with self._buffers_lock:
            self._buffers.setdefault(path, [])
            self._file_locks.setdefault(path, threading.Lock())

    def _flush_buffer(self, path: Path) -> None:
        """Write the buffered records for *path* to disk (thread‑safe)."""
        with self._buffers_lock:
            buffer = self._buffers.get(path, [])
            lock = self._file_locks.setdefault(path, threading.Lock())

        if not buffer or self.dry_run:
            buffer.clear()
            return

        count = len(buffer)
        with lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                for rec in buffer:
                    f.write(rec.to_json() + "\n")
            self._flush_aux(path, buffer)
            buffer.clear()
        log.debug("Flushed %d record(s) to %s", count, path.name)

    _IDLE = object()  # sentinel returned by :meth:`_poll_task` when the queue is idle

    _IDLE = object()  # sentinel returned by :meth:`_poll_task` when the queue is idle

    @staticmethod
    def _poll_task(task_queue: "queue.Queue") -> Any:
        """Return the next task, or the :data:`_IDLE` sentinel when idle.

        A 1 s bounded wait lets workers exit promptly once the queue is drained
        without spinning on ``get()``.
        """
        try:
            return task_queue.get(timeout=1)  # pylint: disable=assignment-from-none
        except queue.Empty:
            return ConcurrentLLMPipeline._IDLE

    def _worker(self, task_queue: "queue.Queue") -> None:
        """Thread target: consume tasks, process them and buffer the results."""
        client = self._make_client()
        ctx = self._make_context()
        try:
            while True:
                task = self._poll_task(task_queue)
                if task is self._IDLE:
                    break
                try:
                    record = self._process(client, ctx, *task)
                    if record is not None:
                        output_path = Path(task[0])
                        self._ensure_buffer(output_path)
                        need_flush = False
                        with self._buffers_lock:
                            buf = self._buffers[output_path]
                            buf.append(record)
                            if len(buf) >= self.batch_save_size:
                                need_flush = True
                        if need_flush:
                            self._flush_buffer(output_path)
                except Exception as exc:  # keep the pool alive on a bad task
                    log.exception("Failed to process task %r: %s", task, exc)
                finally:
                    task_queue.task_done()
        finally:
            client.close()

    def run(self) -> None:
        """Execute the pipeline: validate, build the queue, run workers, flush."""
        self._validate()
        task_queue = self._build_task_queue()

        threads = [
            threading.Thread(target=self._worker, args=(task_queue,), daemon=True)
            for _ in range(self.num_workers)
        ]
        for thread in threads:
            thread.start()

        task_queue.join()
        for thread in threads:
            thread.join()

        with self._buffers_lock:
            paths_to_flush = list(self._buffers.keys())
        for path in paths_to_flush:
            self._flush_buffer(path)
        log.info("Processing finished.")
