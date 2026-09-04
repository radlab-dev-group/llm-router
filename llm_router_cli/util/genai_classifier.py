"""
GenAI classifier app (ported from ``llm-router-utils``, dependency‑light).

:class:`GenAIClassifierApp` walks every ``*.jsonl`` file found in
``dataset_dir`` (plus any explicitly passed ``dataset_paths``), and for each
value of the configured *text column* asks the router (via
``LLMRouterClient.extended_conversation_with_model``) whether each configured
feature (prompt) is present in the text. The LLM is expected to answer with a
JSON object; the answer is stored per record.

Upstream differences (this port):

* No HuggingFace ``datasets`` (``_load_datasets`` / ``HfDatasetHandler``
  removed) and no XLSX branch (``pandas`` / ``openpyxl`` /
  ``convert_jsonl_to_xlsx`` removed). Only local ``*.jsonl`` files are read,
  through :func:`llm_router_cli.util.loaders.read_records`.
* The ``tenacity`` ``@retry`` decorator is gone; the invalid‑JSON retry loop
  is kept, and network retries are handled by the built‑in ``retries`` of
  :class:`LLMRouterClient`.
* ``dataset`` items are plain ``List[Dict]`` instead of a HuggingFace dataset
  or a ``pandas.DataFrame``.
* The hard‑coded default router URL is ``http://localhost:8080``.
"""

from __future__ import annotations

import json
import logging
import queue
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from tqdm import tqdm

from llm_router_lib.client import LLMRouterClient
from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from .json_utils import loads_json
from .loaders import read_records
from .pipeline import ConcurrentLLMPipeline

log = logging.getLogger(__name__)

#: Extra system‑prompt fragment asking the model for a strict JSON answer.
#: Set to ``None`` to disable (kept for parity with the upstream app, which
#: ultimately used ``None``).
_ADDITIONAL_PROMPT_JSON: Optional[str] = None


@dataclass
class AggregatedRecord:
    """One line that will be stored in the JSON‑Lines output file."""

    text: str
    field: str
    features: List[Dict[str, Any]]

    def to_json(self) -> str:
        """Serialize to a JSON string (ASCII‑safe)."""
        return json.dumps(
            {"text": self.text, "field": self.field, "features": self.features},
            ensure_ascii=False,
        )


class GenAIClassifierApp(ConcurrentLLMPipeline):
    """
    High‑level orchestrator for the GenAI classification pipeline.

    Built on the shared :class:`~llm_router_cli.util.pipeline.ConcurrentLLMPipeline`
    (worker pool, buffering, flushing, lifecycle); this class only supplies the
    classification‑specific pieces.

    - Generates a main ``<name>.jsonl`` file with all LLM responses.
    - Generates a ``<name>_clean_labels.jsonl`` file with simplified labels
      for use with the data augmentator.

    (No XLSX export in this port.)
    """

    def __init__(
        self,
        dataset_dir: Path,
        prompts_dir: Path,
        llm_router_url: str,
        model_name: str,
        temperature: float = 0.0,
        llm_router_token: Optional[str] = None,
        llm_router_timeout: int = 10,
        prompts_list: Optional[List[str]] = None,
        batch_save_size: int = 5,
        dry_run: bool = False,
        output_dir: Optional[Path] = None,
        verbose: bool = False,
        num_workers: int = 2,
        n_sample: Optional[int] = 50,
        dataset_paths: Optional[List[Path]] = None,
        text_column_name: str = "Tekst",
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
        self.dataset_dir = Path(dataset_dir)
        self.prompts_dir = Path(prompts_dir)
        self.model_name = model_name
        self.temperature = temperature
        self.prompts_list = list(prompts_list or [])
        self.output_dir = Path(output_dir) if output_dir else None
        self.n_sample = n_sample
        self.dataset_paths = [Path(p) for p in (dataset_paths or [])]
        self.text_column_name = text_column_name

    # ------------------------------------------------------------------ #
    # Loading
    # ------------------------------------------------------------------ #
    def _load_local_datasets(
        self, fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Load every ``*.jsonl`` file in ``dataset_dir`` (plus any explicit
        ``dataset_paths``) into ``List[Dict]`` records.
        """
        loaded: List[Dict[str, Any]] = []

        jsonl_files: List[Path] = list(self.dataset_dir.glob("*.jsonl"))
        for extra in self.dataset_paths:
            if extra.is_file() and extra not in jsonl_files:
                jsonl_files.append(extra)

        if not jsonl_files:
            log.warning("No local .jsonl files found in %s", self.dataset_dir)
            return loaded

        log.info("Found %d local file(s) in dataset directory", len(jsonl_files))

        for data_file in jsonl_files:
            try:
                dataset_records = read_records(data_file, "jsonl")
                columns = list(dataset_records[0].keys()) if dataset_records else []
                effective_fields = fields or columns
                ds_name = data_file.stem
                log.info(
                    "Loading dataset %s (from %s) with fields: %s",
                    ds_name,
                    data_file.suffix,
                    effective_fields,
                )
                loaded.append(
                    {
                        "name": ds_name,
                        "fields": effective_fields,
                        "dataset": dataset_records,
                    }
                )
            except Exception as exc:  # pragma: no cover - runtime safeguard
                log.exception("Failed to load local file %s: %s", data_file, exc)
        return loaded

    # ------------------------------------------------------------------ #
    # Classification
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
        """Parse an LLM answer as a JSON object (``None`` when not possible)."""
        try:
            obj = loads_json(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
        return obj if isinstance(obj, dict) else None

    def _classify_text(
        self,
        llm_client: LLMRouterClient,
        prompt_handler: PromptHandler,
        text: str,
        feature_name: str,
        retry_when_invalid_json: int = 5,
    ) -> Dict[str, Any]:
        """
        Call the LLM for a single ``(text, feature)`` pair and return the
        parsed JSON object (``{}`` when the model never produced valid JSON).
        """
        prompt_str = prompt_handler.get_prompt(feature_name)

        if _ADDITIONAL_PROMPT_JSON and _ADDITIONAL_PROMPT_JSON.strip():
            prompt_str += f"\n{_ADDITIONAL_PROMPT_JSON}"

        parsed: Optional[Dict[str, Any]] = None
        raw_json = ""
        for attempt in range(retry_when_invalid_json, 0, -1):
            response = llm_client.extended_conversation_with_model(
                user_last_statement=text,
                system_prompt=prompt_str,
                model=self.model_name,
                temperature=self.temperature,
            )
            raw_json = (response.response or "").strip()
            candidate = self._parse_llm_json(raw_json)
            if candidate is not None:
                parsed = candidate
                break
            log.warning(
                "Invalid JSON from LLM for text %r... (feature %s), "
                "%d attempt(s) left",
                text[:20],
                feature_name,
                attempt - 1,
            )
            log.debug("Raw LLM response: %s", raw_json)

        if parsed is None:
            return {}
        if self.verbose and parsed:
            parsed["_raw_response"] = raw_json
        return parsed

    # ------------------------------------------------------------------ #
    # Resume support
    # ------------------------------------------------------------------ #
    @staticmethod
    def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
        """Yield the JSON objects stored in *path* (malformed lines skipped)."""
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.debug("Skipping malformed line in %s", path)
                    continue
                if isinstance(obj, dict):
                    yield obj

    def _load_existing_texts(self, path: Path) -> Set[Tuple[str, str]]:
        """
        Return the set of ``(field, text)`` already present in *path*, and make
        sure the companion labels file contains every record from the main
        file (backfilling any that are missing).
        """
        seen: Set[Tuple[str, str]] = set()
        if not path.is_file():
            return seen

        main_records: List[Dict[str, Any]] = []
        for obj in self._iter_jsonl(path):
            txt = obj.get("text")
            fld = obj.get("field")
            if isinstance(txt, str) and isinstance(fld, str):
                seen.add((fld, txt))
                main_records.append(obj)

        aug_path = path.with_name(f"{path.stem}_clean_labels.jsonl")
        seen_aug: Set[Tuple[str, str]] = set()
        if aug_path.is_file():
            for obj in self._iter_jsonl(aug_path):
                txt = obj.get("text")
                fld = obj.get("original_field")
                if isinstance(txt, str) and isinstance(fld, str):
                    seen_aug.add((fld, txt))

        missing = [
            rec
            for rec in main_records
            if (rec.get("field"), rec.get("text")) not in seen_aug
        ]
        if missing:
            log.info(
                "Converting %d missing records to augmentation format in %s",
                len(missing),
                aug_path.name,
            )
            with aug_path.open("a", encoding="utf-8") as handle:
                for rec in missing:
                    aug_rec = {
                        "text": rec.get("text"),
                        "labels": self._extract_labels(rec.get("features", [])),
                        "original_field": rec.get("field"),
                    }
                    handle.write(json.dumps(aug_rec, ensure_ascii=False) + "\n")

        log.info(
            "Loaded %d previously processed records from %s", len(seen), path.name
        )
        return seen

    @staticmethod
    def _extract_labels(features: List[Dict[str, Any]]) -> List[Any]:
        """Collect the labels (classes) produced for a record's features."""
        labels: List[Any] = []
        for feat in features:
            resp = feat.get("response", {})
            if "class" in resp:
                labels.append(resp["class"])
            elif resp.get("exists") is True:
                labels.append(feat["name"])
        return labels

    # ------------------------------------------------------------------ #
    # Pipeline hooks (implemented on top of ConcurrentLLMPipeline)
    # ------------------------------------------------------------------ #
    def _validate(self) -> None:
        """Validate inputs, resolve the prompt list and log startup info."""
        if not self.dataset_dir.is_dir():
            raise ValueError(f"Dataset directory does not exist: {self.dataset_dir}")
        if not self.prompts_dir.is_dir():
            raise ValueError(f"Prompts directory does not exist: {self.prompts_dir}")
        if not self.output_dir:
            raise ValueError("Output directory is not given.")
        if not self.output_dir.is_dir():
            raise ValueError(f"Output directory does not exist: {self.output_dir}")

        # Validate the prompts directory early (raises on unreadable prompts).
        handler = PromptHandler(str(self.prompts_dir))
        self.prompts_list = list(handler.list_prompts().keys())

        self._log_startup_info()

    def _make_context(self) -> PromptHandler:
        """One shared :class:`PromptHandler` per worker."""
        return PromptHandler(str(self.prompts_dir))

    def _progress_description(self) -> str:
        """Label for the run‑wide progress bar."""
        return "Classifying"

    def _build_task_queue(self) -> queue.Queue[Any]:
        """Load every local dataset and enqueue its unprocessed (field, text)."""
        all_datasets = self._load_local_datasets(fields=[self.text_column_name])
        task_q: queue.Queue[Any] = queue.Queue()
        for ds_item in all_datasets:
            self._process_dataset(ds_item, task_q)
        return task_q

    def _process(
        self,
        client: LLMRouterClient,
        ctx: PromptHandler,
        output_path: Path,
        field: str,
        text: str,
    ) -> AggregatedRecord:
        """Classify a single text against every configured feature (prompt)."""
        feature_responses: List[Dict[str, Any]] = []
        for feature_name in self.prompts_list:
            llm_response = self._classify_text(
                client,
                ctx,
                text,
                feature_name,
                retry_when_invalid_json=5,
            )
            feature_responses.append(
                {"name": feature_name, "response": llm_response}
            )
        return AggregatedRecord(text=text, field=field, features=feature_responses)

    def _flush_aux(self, path: Path, records: List[AggregatedRecord]) -> None:
        """Write the simplified ``<stem>_clean_labels.jsonl`` companion file."""
        aug_path = path.with_name(f"{path.stem}_clean_labels.jsonl")
        with aug_path.open("a", encoding="utf-8") as f:
            for rec in records:
                aug_rec = {
                    "text": rec.text,
                    "labels": self._extract_labels(rec.features),
                    "original_field": rec.field,
                }
                f.write(json.dumps(aug_rec, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ #
    # Task preparation
    # ------------------------------------------------------------------ #
    def _process_dataset(
        self, ds_item: Dict[str, Any], task_queue: queue.Queue[Any]
    ) -> None:
        """Scan a dataset (``List[Dict]``) and enqueue unprocessed (field, text)."""
        ds_name = ds_item["name"]
        fields = ds_item["fields"]
        dataset: List[Dict[str, Any]] = ds_item["dataset"]

        log.info("Preparing tasks for dataset %s (fields: %s)", ds_name, fields)

        out_dir = self.output_dir or self.dataset_dir
        output_path = out_dir / f"{ds_name.replace('/', '__')}.jsonl"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        already_done = self._load_existing_texts(output_path)
        self._ensure_buffer(output_path)

        rng = random.Random()
        for field in tqdm(fields, desc=f"{ds_name} fields", leave=False):
            values = [record[field] for record in dataset if field in record]
            rng.shuffle(values)

            if self.n_sample is None or self.n_sample <= 0:
                sampled_values = values
            else:
                sampled_values = values[: self.n_sample]

            for value in sampled_values:
                key = (field, str(value))
                if key in already_done:
                    continue
                already_done.add(key)
                task_queue.put((output_path, field, str(value)))

    def _log_startup_info(self) -> None:
        """Log the router version (best effort) and, when verbose, the config."""
        try:
            client = LLMRouterClient(
                self.llm_router_url,
                token=self.llm_router_token,
                timeout=self.llm_router_timeout,
            )
            try:
                version_info = client.version()
            finally:
                client.close()
            log.info("Using LLMRouter version %s", version_info.version or "unknown")
        except Exception as exc:  # pragma: no cover - network dependent
            log.warning("Could not fetch LLMRouter version: %s", exc)

        if self.verbose:
            log.debug("Full configuration: %s", self.__dict__)
