"""
Text translation app (ported from ``llm-router-utils``, dependency‑light).

Logic is the same as the original :class:`TextTranslationService` /
:class:`TranslateApp` — flatten the accepted fields of the records into a flat
list of strings, send them to the router in batches (optionally with a thread
pool), splice the translations back into the records, and emit the result.

Differences vs. the upstream version:

* Data is read with :func:`llm_router_cli.util.loaders.read_records`
  (local JSON/JSONL only — no HuggingFace ``datasets``).
* **Results are written to disk** (the upstream CLI printed nothing). Without
  ``-o/--output`` each input file ``<stem>`` produces ``<stem>.translated.jsonl``
  right next to it; with ``-o`` every record from every input goes to that one
  file. In **both** cases the input files are left untouched.
"""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from tqdm import tqdm

from llm_router_lib.client import LLMRouterClient

from .loaders import read_records

log = logging.getLogger(__name__)


class TextTranslationService:
    """Thin wrapper around :class:`LLMRouterClient` for translation calls."""

    def __init__(
        self,
        router_host: str,
        model: str,
        token: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.client = LLMRouterClient(
            api=router_host, timeout=timeout, retries=2, token=token
        )
        self.model = model

    def translate(self, texts: List[str]) -> List[str]:
        """Send ``texts`` to the router and return the translated strings."""
        response = self.client.translate(model=self.model, texts=texts)
        return [item.translated for item in response.response]

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.client.close()


class TranslateApp:
    """
    High‑level translation orchestrator usable from the CLI or as a library.

    The ``args`` namespace is expected to expose at least:
    ``dataset_path`` (list), ``dataset_type`` (optional), ``accept_field``
    (list, may be empty), ``llm_router_host``, ``model``, ``llm_router_token``,
    ``llm_router_timeout``, ``num_workers``, ``batch_size`` and (optional)
    ``output``.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.accept_fields: List[str] = list(args.accept_field or [])
        self.dataset_paths: List[str] = list(args.dataset_path or [])
        self.dataset_type: Optional[str] = getattr(args, "dataset_type", None)
        self.output: Optional[Path] = (
            Path(args.output) if getattr(args, "output", None) else None
        )

        self.service = TextTranslationService(
            router_host=args.llm_router_host,
            model=args.model,
            token=getattr(args, "llm_router_token", None),
            timeout=getattr(args, "llm_router_timeout", 10),
        )

        self.num_workers = int(getattr(args, "num_workers", 1))
        self.batch_size = int(getattr(args, "batch_size", 8))

        # Collected for backward‑compatibility / library use.
        self.translations: List[str] = []
        # The paths actually written during :meth:`run`.
        self.written_paths: List[Path] = []

    # ------------------------------------------------------------------ #
    # Record flattening / reconstruction
    # ------------------------------------------------------------------ #
    def _flatten_records(
        self, records: List[Dict[str, Any]]
    ) -> Tuple[List[str], List[Tuple[int, str]]]:
        """
        Split records into a flat list of strings plus positions mapping each
        string back to ``(record_index, field_name)``.
        """
        flat_texts: List[str] = []
        positions: List[Tuple[int, str]] = []
        for idx, rec in enumerate(records):
            for field in self.accept_fields:
                if field in rec:
                    flat_texts.append(str(rec[field]))
                    positions.append((idx, field))
        return flat_texts, positions

    def _select_output_records(
        self, records: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Return the records restricted to the accepted fields.

        When no ``--accept-field`` was given, all fields are retained (matching
        the CLI help text "if omitted all fields are kept").
        """
        if self.accept_fields:
            return [
                {k: v for k, v in rec.items() if k in self.accept_fields}
                for rec in records
            ]
        return [dict(rec) for rec in records]

    def _batch_texts(self, texts: List[str]) -> List[List[str]]:
        """Split *texts* into chunks of ``batch_size``."""
        if self.batch_size <= 0:
            return [texts] if texts else []
        return [
            texts[i : i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]

    # ------------------------------------------------------------------ #
    # Translation step (single‑ / multi‑threaded)
    # ------------------------------------------------------------------ #
    def _translate_batches(self, batches: List[List[str]]) -> List[str]:
        """Translate every batch and return a flat, order‑preserving list."""
        if self.num_workers <= 1:
            ordered: List[List[str]] = [
                self.service.translate(batch)
                for batch in tqdm(
                    batches, desc="Translating (single thread)", unit="batch"
                )
            ]
        else:
            ordered = [[] for _ in batches]
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                future_to_idx = {
                    executor.submit(self.service.translate, batch): idx
                    for idx, batch in enumerate(batches)
                }
                pbar = tqdm(
                    total=len(batches),
                    desc="Translating (multi thread)",
                    unit="batch",
                )
                for future in as_completed(future_to_idx):
                    ordered[future_to_idx[future]] = future.result()
                    pbar.update(1)
                pbar.close()
        return [text for batch in ordered for text in batch]

    def _translate_records(
        self, records: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Translate the accepted fields of *records* in place and return the
        output records (restricted to the accepted fields).
        """
        flat_texts, positions = self._flatten_records(records)
        if flat_texts:
            batches = self._batch_texts(flat_texts)
            flat_results = self._translate_batches(batches)
            for (rec_idx, field_name), translated in zip(positions, flat_results):
                records[rec_idx][field_name] = translated
        return self._select_output_records(records)

    # ------------------------------------------------------------------ #
    # Output writing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
        """Write *records* to *path* as JSON Lines (creating parent dirs)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")

    @classmethod
    def _output_path_for_input(cls, input_path: Path) -> Path:
        """Return ``<stem>.translated.jsonl`` next to *input_path*."""
        input_path = Path(input_path)
        return input_path.with_name(f"{input_path.stem}.translated.jsonl")

    def _register_output(
        self, records: List[Dict[str, Any]], out_path: Path
    ) -> None:
        """Record *records* (written to *out_path*) for library use."""
        self.translations.extend(json.dumps(r, ensure_ascii=False) for r in records)
        self.written_paths.append(out_path)

    # ------------------------------------------------------------------ #
    # Main workflow
    # ------------------------------------------------------------------ #
    def _translated_inputs(self) -> Iterator[Tuple[Path, List[Dict[str, Any]]]]:
        """Yield ``(input_path, translated_records)`` for every input file."""
        for raw_path in self.dataset_paths:
            input_path = Path(raw_path)
            records = read_records(input_path, self.dataset_type)
            yield input_path, self._translate_records(records)

    def run(self) -> None:
        """Execute the translation pipeline and write the output files."""
        if not self.dataset_paths:
            raise ValueError("No dataset paths were provided.")

        self.translations = []
        self.written_paths = []

        if self.output is not None:
            all_records: List[Dict[str, Any]] = []
            for _input_path, out_records in self._translated_inputs():
                all_records.extend(out_records)
            self._write_jsonl(self.output, all_records)
            self._register_output(all_records, self.output)
            log.info(
                "Translated %d record(s) from %d input(s) -> %s",
                len(all_records),
                len(self.dataset_paths),
                self.output,
            )
        else:
            for input_path, out_records in self._translated_inputs():
                out_path = self._output_path_for_input(input_path)
                self._write_jsonl(out_path, out_records)
                self._register_output(out_records, out_path)
                log.info(
                    "Translated %d record(s) from %s -> %s",
                    len(out_records),
                    input_path,
                    out_path,
                )

    def close(self) -> None:
        """Release the underlying HTTP client."""
        self.service.close()
