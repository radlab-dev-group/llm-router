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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Set, Tuple

from llm_router_lib.client import LLMRouterClient

from .json_utils import loads_json
from .loaders import read_records
from .pipeline import ConcurrentLLMPipeline
from .retry import with_retries

log = logging.getLogger(__name__)


@dataclass
class AugmentedRecord:
    """One line that will be stored in the JSON‑Lines output file."""

    original_text: str
    labels: List[str]
    augmented_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    #: Keys that a merged LLM payload must never overwrite.
    RESERVED_KEYS: ClassVar[Tuple[str, ...]] = (
        "original_text",
        "labels",
        "metadata",
    )

    def _parsed_augmented(self) -> Any:
        """Parse ``augmented_text`` as JSON (code‑fence tolerant), or ``None``."""
        try:
            return loads_json(self.augmented_text or "")
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

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

        parsed = self._parsed_augmented()
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if key not in self.RESERVED_KEYS:
                    data[key] = value
        elif isinstance(parsed, list):
            data["augmented_results"] = parsed
        else:
            data["augmented_text"] = self.augmented_text
        return data

    def to_json(self) -> str:
        """Serialize to a JSON string (ASCII‑safe)."""
        return json.dumps(self.to_dict(), ensure_ascii=False)


class GenAIDataAugmentationApp(ConcurrentLLMPipeline):
    """
    High‑level orchestrator for the GenAI data augmentation pipeline.

    Built on the shared :class:`~llm_router_cli.util.pipeline.ConcurrentLLMPipeline`
    (worker pool, buffering, flushing, lifecycle); this class only supplies the
    augmentation‑specific pieces.

    - Loads a local JSONL dataset.
    - Samples original data for the given labels.
    - Uses the LLM to generate augmented versions of the samples.
    - Saves the results as JSONL (no XLSX in this port).

    The constructor is intentionally wide: each argument maps 1:1 to a CLI
    flag (see :mod:`llm_router_cli.cli.commands.util`), so a self-documenting
    explicit signature is preferable to a packed config object.
    """

    def __init__(  # pylint: disable=too-many-arguments
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
        super().__init__(
            llm_router_url=llm_router_url,
            llm_router_token=llm_router_token,
            llm_router_timeout=llm_router_timeout,
            batch_save_size=batch_save_size,
            dry_run=dry_run,
            verbose=verbose,
            num_workers=num_workers,
        )
        self.dataset_path = Path(dataset_path)
        self.prompt_path = Path(prompt_path)
        self.labels = [L.strip() for L in labels if L and L.strip()]
        self.model_name = model_name
        self.temperature = temperature
        self.n_samples = n_samples
        self.n_examples = n_examples
        self.samples_as_examples = samples_as_examples
        self.output_dir = Path(output_dir) if output_dir else None
        self.text_column_name = text_column_name
        self.label_column_name = label_column_name
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_wait = float(retry_wait)

        # Per‑worker context, resolved in :meth:`_build_task_queue`.
        self._prompt_content = ""
        self._all_samples_info = ""

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def _load_dataset(self) -> List[Dict[str, Any]]:
        """Load the dataset (local JSONL/JSON) as a list of record dicts."""
        log.info("Loading dataset from %s", self.dataset_path)
        records = read_records(self.dataset_path)

        present_keys: Set[str] = set()
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

        response = with_retries(
            lambda: llm_client.extended_conversation_with_model(
                user_last_statement=text,
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
    # Pipeline hooks (implemented on top of ConcurrentLLMPipeline)
    # ------------------------------------------------------------------ #
    def _validate(self) -> None:
        """Validate the dataset and prompt files exist before running."""
        if not self.dataset_path.is_file():
            raise ValueError(f"Dataset file does not exist: {self.dataset_path}")
        if not self.prompt_path.is_file():
            raise ValueError(f"Prompt file does not exist: {self.prompt_path}")

    def _make_context(self) -> Tuple[str, str]:
        """Per-worker context: the resolved prompt and the sample examples."""
        return self._prompt_content, self._all_samples_info

    def _progress_description(self) -> str:
        """Label for the run‑wide progress bar."""
        return "Augmenting"

    def _build_task_queue(self) -> queue.Queue[Any]:
        """Load the dataset, build the sample context and enqueue the tasks."""
        records = self._load_dataset()
        self._prompt_content = self.prompt_path.read_text(encoding="utf-8")

        out_dir = self.output_dir or self.dataset_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{self.dataset_path.stem}_augmented.jsonl"
        self._ensure_buffer(output_path)

        task_queue: queue.Queue[Any] = queue.Queue()
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

        self._all_samples_info = "".join(
            f"Przyk\u0142ad {i}:\nTekst: {sample['text']}\n"
            f"Klasy: {', '.join(sample['labels'])}\n\n"
            for i, sample in enumerate(example_samples, 1)
        )
        return task_queue

    def _process(
        self,
        client: LLMRouterClient,
        ctx: Tuple[str, str],
        output_path: Path,
        labels: List[str],
        text: str,
    ) -> Optional[AugmentedRecord]:
        """Augment a single text and wrap the result in a record."""
        prompt, all_samples_info = ctx
        try:
            augmented_text = self._augment_text(
                client, prompt, text, labels, all_samples_info
            )
        except Exception as exc:
            log.exception("Failed to augment text for labels %s: %s", labels, exc)
            return None
        return AugmentedRecord(
            original_text=text,
            labels=labels,
            augmented_text=augmented_text,
            metadata={
                "model": self.model_name,
                "temperature": self.temperature,
            },
        )

    def _flush_aux(self, path: Path, records: List[AugmentedRecord]) -> None:
        """Write the ``<stem>-train.jsonl`` convenience file for *records*."""
        train_path = path.with_name(f"{path.stem}-train.jsonl")
        with train_path.open("a", encoding="utf-8") as f_train:
            for rec in records:
                rec_dict = rec.to_dict()
                examples = rec_dict.get("augmented_examples", [])
                if not isinstance(examples, list):
                    continue
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
