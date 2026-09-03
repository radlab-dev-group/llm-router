"""
Lightweight, dependency-free dataset loaders for the ``util`` apps.

Both :class:`~llm_router_cli.util.genai_classifier.GenAIClassifierApp` and
:class:`~llm_router_cli.util.genai_data_augmentation.GenAIDataAugmentationApp`
(and optionally
:class:`~llm_router_cli.util.translate.TranslateApp`) read their data through
:func:`read_records`, which understands exactly two on-disk formats:

* **JSON**  – a single JSON document that is either an object or a list of
  objects.
* **JSONL** – newline-delimited JSON; one object per line. Empty lines are
  skipped and malformed lines are reported via the ``logging`` facility and
  skipped (so a single bad line never aborts the whole run).

No third‑party data libraries (``pandas`` / ``openpyxl`` / HuggingFace
``datasets``) are imported here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger(__name__)

Record = Dict[str, Any]


def _infer_dataset_type(path: Path) -> str:
    """
    Infer the dataset type from *path*'s file extension.

    Parameters
    ----------
    path : Path
        The file to classify.

    Returns
    -------
    str
        ``"json"`` or ``"jsonl"``.

    Raises
    ------
    ValueError
        If the extension is not one of the supported ones.
    """
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return "jsonl"
    if suffix == ".json":
        return "json"
    raise ValueError(
        f"Cannot infer dataset type from extension '{path.suffix}' of {path}; "
        "expected '.json' or '.jsonl'."
    )


def _read_jsonl(path: Path) -> List[Record]:
    """
    Read a JSONL file into a list of dictionaries.

    Blank lines are skipped silently. Lines that cannot be decoded as JSON are
    logged as a warning and skipped. Lines that decode to something other than
    an object (e.g. a bare string or number) are skipped as well.
    """
    records: List[Record] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(
                    "Skipping invalid JSON on line %d of %s: %s",
                    line_number,
                    path,
                    exc,
                )
                continue
            if isinstance(obj, dict):
                records.append(obj)
            elif isinstance(obj, list):
                # A single line containing a JSON array of objects.
                for item in obj:
                    if isinstance(item, dict):
                        records.append(item)
            else:
                log.warning(
                    "Skipping non-object JSON on line %d of %s", line_number, path
                )
    return records


def _read_json(path: Path) -> List[Record]:
    """
    Read a single JSON document into a list of dictionaries.

    A top‑level object is returned as a one‑element list; a top‑level array is
    returned as its list of object elements (non‑object elements are skipped).
    """
    with path.open("r", encoding="utf-8") as handle:
        try:
            content = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if isinstance(content, dict):
        return [content]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    raise ValueError(f"Unsupported top-level JSON type in {path}: {type(content)}")


def read_records(
    path: Union[str, Path], dataset_type: Optional[str] = None
) -> List[Record]:
    """
    Read a local JSON or JSONL file and return its records as a list of dicts.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the dataset file on disk.
    dataset_type : Optional[str]
        Explicit dataset type – ``"json"`` or ``"jsonl"``. If ``None`` (the
        default) the type is inferred from the file extension.

    Returns
    -------
    List[Dict[str, Any]]
        A flat list of record dictionaries (empty when the file has no
        records).

    Raises
    ------
    ValueError
        If the dataset type cannot be determined, or the (single-document) JSON
        file is malformed.
    FileNotFoundError
        If *path* does not exist.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    dtype = (dataset_type or _infer_dataset_type(file_path)).lower()
    if dtype == "jsonl":
        return _read_jsonl(file_path)
    if dtype == "json":
        return _read_json(file_path)
    raise ValueError(f"Unsupported dataset type '{dtype}' for file {file_path}")
