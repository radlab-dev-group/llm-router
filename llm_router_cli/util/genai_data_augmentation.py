"""
GenAI data augmentation app (ported from ``llm-router-utils``, dependency‑light).

:class:`GenAIDataAugmentationApp` reads a local JSONL dataset, samples a few
records per label, and asks the router to generate augmented examples of the
texts. Results are written as ``<stem>_augmented.jsonl`` plus a
``<stem>_augmented-train.jsonl`` convenience file.

Upstream differences (this port):

* ``_load_dataset`` returns a ``List[Dict]`` read with
  :func:`llm_router_cli.util.loaders.read_records` — no ``pandas`` / XLSX.
* The ``run()`` workflow is refactored from ``DataFrame`` operations to plain
  list/dict operations (``df.columns`` → key check, boolean masking → list
  filter, ``subset.sample(n)`` → ``random.sample``, ``iterrows()`` → record
  iteration, ``row.get(...)`` → ``dict.get``).
* The ``tenacity`` ``@retry`` decorator on ``_augment_text`` is replaced with
  :func:`llm_router_cli.util.retry.with_retries`.
* XLSX export is removed entirely.
* The hard‑coded default router URL is ``http://localhost:8080``.
"""

from __future__ import annotations

import ast
import json
import logging
import queue
import random
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_router_lib.client import LLMRouterClient

from .loaders import read_records
from .retry import with_retries

log = logging.getLogger(__name__)


@dataclass
class AugmentedRecord:
    """One line that will be stored in the JSON‑Lines output file."""

    original_text: str
    labels: List[str]
    augmented_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to a dict for serialization, merging a parsed
        ``augmented_text`` (JSON object / array) when possible.
        """
        data: Dict[str, Any] = {
            "original_text": self.original_text,
            "labels": self.labels,
            "metadata": self.metadata,
        }

        try:
            clean_text = self.augmented_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

            parsed_augmented = json.loads(clean_text)
            if isinstance(parsed_augmented, dict):
                data.update(parsed_augmented)
            elif isinstance(parsed_augmented, list):
                data["augmented_results"] = parsed_augmented
            else:
                data["augmented_text"] = self.augmented_text
        except (json.JSONDecodeError, TypeError):
            data["augmented_text"] = self.augmented_text
        return data

    def to_json(self) -> str:
        """Serialize to a JSON string (ASCII‑safe)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class GenAIDataAugmentationApp:
    """
    High‑level orchestrator for the GenAI data augmentation pipeline.

    - Loads a local JSONL dataset.
    - Samples original data for the given labels.
    - Uses the LLM to generate augmented versions of the samples.
    - Saves the results as JSONL (no XLSX in this port).
    """

    def __init__(
        self,
        dataset_path: Path,
        prompt_path: Path,
        labels: List[str],
        llm_router_url: str,
        model_name: str,
        llm_router_token: Optional[str] = None,
        llm_router_timeout: int = 10,
        temperature: float = 0.7,
        n_samples: int = 5,
        n_examples: int = 3,
        samples_as_examples: int = 5,
        batch_save_size: int = 5,
        dry_run: bool = False,
        output_dir: Optional[Path] = None,
        verbose: bool = False,
        num_workers: int = 2,
        text_column_name: str = "Tekst",
        label_column_name: str = "label",
        retry_attempts: int = 5,
        retry_wait: float = 0.0,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.prompt_path = Path(prompt_path)
        self.labels = [L.strip() for L in labels if L and L.strip()]
        self.llm_router_url = llm_router_url
        self.llm_router_token = llm_router_token
        self.llm_router_timeout = llm_router_timeout
        self.model_name = model_name
        self.temperature = temperature
        self.n_samples = n_samples
        self.n_examples = n_examples
        self.samples_as_examples = samples_as_examples
        self.batch_save_size = batch_save_size
        self.dry_run = dry_run
        self.output_dir = Path(output_dir) if output_dir else None
        self.verbose = verbose
        self.num_workers = max(1, int(num_workers))
        self.text_column_name = text_column_name
        self.label_column_name = label_column_name
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_wait = float(retry_wait)

        self._buffers: Dict[Path, List[AugmentedRecord]] = {}
        self._file_locks: Dict[Path, threading.Lock] = {}
        self._buffers_lock = threading.Lock()

        if self.verbose:
            log.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def _load_dataset(self) -> List[Dict[str, Any]]:
        """Load the dataset (local JSONL/JSON) as a list of record dicts."""
        log.info("Loading dataset from %s", self.dataset_path)
        records = read_records(self.dataset_path)

        present_keys: set = set()
        for rec in records:
            present_keys.update(rec.keys())

        if self.text_column_name not in present_keys:
            raise ValueError(
                f"Column '{self.text_column_name}' not found in dataset "
                f"(available: {sorted(present_keys)})"
            )
        if self.label_column_name not in present_keys:
            log.warning(
                "Column '%s' not found; label filtering will match nothing.",
                self.label_column_name,
            )
        return records

    # ------------------------------------------------------------------ #
    # Label helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _coerce_label_value(val: Any) -> Any:
        """
        Interpret a raw label value, transparently decoding the *string*
        representation of a Python list (as produced by XLSX/JSONL exports).
        """
        if (
            isinstance(val, str)
            and val.strip().startswith("[")
            and val.strip().endswith("]")
        ):
            try:
                return ast.literal_eval(val)
            except (ValueError, SyntaxError):
                return val
        return val

    def _matches_label(self, raw_val: Any, label: str) -> bool:
        """Return ``True`` when *label* is one of the record's labels."""
        val = self._coerce_label_value(raw_val)
        if isinstance(val, list):
            return label in [str(v).strip() for v in val]
        return str(val).strip() == label

    def _normalize_labels(self, raw_val: Any) -> List[str]:
        """Normalize a raw label value to a clean list of label strings."""
        val = self._coerce_label_value(raw_val)
        if not isinstance(val, list):
            val = [str(val).strip()]
        else:
            val = [str(L).strip() for L in val]
        return [L for L in val if L in self.labels]

    # ------------------------------------------------------------------ #
    # LLM call
    # ------------------------------------------------------------------ #
    def _augment_text(
        self,
        llm_client: LLMRouterClient,
        prompt: str,
        text: str,
        labels: List[str],
        all_samples_info: str = "",
    ) -> str:
        """Call the LLM (with retries) to augment a single text."""
        final_prompt = prompt.replace(
            "{CLASS_LIST_PLACEHOLDER}", ", ".join(self.labels)
        )
        final_prompt = final_prompt.replace(
            "{SAMPLES_PER_CLASS_PLACEHOLDER}", str(self.n_examples)
        )
        final_prompt = final_prompt.replace(
            "{CLASS_EXAMPLES_PLACEHOLDER}", all_samples_info
        )

        user_input = text
        response = with_retries(
            lambda: llm_client.extended_conversation_with_model(
                user_last_statement=user_input,
                system_prompt=final_prompt,
                model=self.model_name,
                temperature=self.temperature,
            ),
            attempts=self.retry_attempts,
            wait=self.retry_wait,
            name=f"augment({labels!r})",
        )
        return (response.response or "").strip()

    # ------------------------------------------------------------------ #
    # Buffering / flushing
    # ------------------------------------------------------------------ #
    def _flush_buffer(self, path: Path) -> None:
        """Write buffered records to disk and to the ``-train`` file."""
        train_path = path.with_name(f"{path.stem}-train.jsonl")

        with self._file_locks[path]:
            with self._buffers_lock:
                records = self._buffers.get(path, [])
                if not records:
                    return
                self._buffers[path] = []

            if self.dry_run:
                return

            log.debug("Flushing %d records to %s", len(records), path)
            with (
                path.open("a", encoding="utf-8") as f,
                train_path.open("a", encoding="utf-8") as f_train,
            ):
                for rec in records:
                    f.write(rec.to_json() + "\n")

                    rec_dict = rec.to_dict()
                    examples = rec_dict.get("augmented_examples", [])
                    if isinstance(examples, list):
                        for ex in examples:
                            if isinstance(ex, str):
                                train_rec = {"text": ex, "labels": rec.labels}
                                f_train.write(
                                    json.dumps(train_rec, ensure_ascii=False) + "\n"
                                )
                            elif isinstance(ex, dict) and "text" in ex:
                                train_rec = {
                                    "text": ex["text"],
                                    "labels": ex.get("labels", rec.labels),
                                }
                                f_train.write(
                                    json.dumps(train_rec, ensure_ascii=False) + "\n"
                                )

    # ------------------------------------------------------------------ #
    # Worker
    # ------------------------------------------------------------------ #
    def _worker(
        self, task_queue: "queue.Queue", prompt: str, all_samples_info: str
    ) -> None:
        """Worker thread for processing augmentation tasks."""
        llm_client = LLMRouterClient(
            self.llm_router_url,
            token=self.llm_router_token,
            timeout=self.llm_router_timeout,
        )

        try:
            while True:
                try:
                    task = task_queue.get(timeout=1)
                except queue.Empty:
                    break

                output_path, labels, text = task

                try:
                    augmented_text = self._augment_text(
                        llm_client, prompt, text, labels, all_samples_info
                    )
                    record = AugmentedRecord(
                        original_text=text,
                        labels=labels,
                        augmented_text=augmented_text,
                        metadata={
                            "model": self.model_name,
                            "temperature": self.temperature,
                        },
                    )

                    need_flush = False
                    with self._buffers_lock:
                        self._buffers[output_path].append(record)
                        if len(self._buffers[output_path]) >= self.batch_save_size:
                            need_flush = True

                    if need_flush:
                        self._flush_buffer(output_path)

                except Exception as exc:
                    log.exception(
                        "Failed to augment text for labels %s: %s", labels, exc
                    )
                finally:
                    task_queue.task_done()
        finally:
            llm_client.close()

    # ------------------------------------------------------------------ #
    # Main workflow
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        """Run the augmentation pipeline."""
        records = self._load_dataset()

        with open(self.prompt_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()

        out_dir = self.output_dir or self.dataset_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{self.dataset_path.stem}_augmented.jsonl"

        with self._buffers_lock:
            self._buffers[output_path] = []
            self._file_locks[output_path] = threading.Lock()

        task_queue: "queue.Queue" = queue.Queue()
        example_samples: List[Dict[str, Any]] = []

        for label in self.labels:
            subset = [
                rec
                for rec in records
                if self._matches_label(rec.get(self.label_column_name), label)
            ]

            if not subset:
                log.warning("No samples found for label: %s", label)
                continue

            n = (
                len(subset)
                if self.n_samples <= 0
                else min(len(subset), self.n_samples)
            )
            sampled = random.sample(subset, n)

            n_ex = (
                len(subset)
                if self.samples_as_examples <= 0
                else min(len(subset), self.samples_as_examples)
            )
            sampled_for_context = random.sample(subset, n_ex)

            for row in sampled_for_context:
                text_ex = str(row[self.text_column_name])
                row_labels_ex = self._normalize_labels(
                    row.get(self.label_column_name, [label])
                )
                example_samples.append({"text": text_ex, "labels": row_labels_ex})

            log.info("Enqueuing %d samples for label: %s", n, label)
            for row in sampled:
                text = str(row[self.text_column_name])
                row_labels = self._normalize_labels(
                    row.get(self.label_column_name, [label])
                )
                task_queue.put((output_path, row_labels, text))

        if task_queue.empty():
            log.warning("No tasks to process.")
            return

        all_samples_info = ""
        for i, sample in enumerate(example_samples, 1):
            all_samples_info += (
                f"Przykład {i}:\nTekst: {sample['text']}\n"
                f"Klasy: {', '.join(sample['labels'])}\n\n"
            )

        threads: List[threading.Thread] = []
        for _ in range(self.num_workers):
            t = threading.Thread(
                target=self._worker,
                args=(task_queue, prompt_content, all_samples_info),
            )
            t.start()
            threads.append(t)

        task_queue.join()
        for t in threads:
            t.join()

        self._flush_buffer(output_path)
        log.info("Augmentation finished. Output saved to %s", output_path)
