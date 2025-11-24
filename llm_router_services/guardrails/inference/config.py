from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class GuardrailModelConfig(ABC):
    """
    Abstract base class that defines the configuration interface required by a
    guardrail model.  Concrete implementations must provide the three fields
    used by :class:`TextClassificationGuardrail`:

    * ``pipeline_batch_size`` – size of batches sent to the HF pipeline.
    * ``min_score_for_safe`` – threshold below which a “SAFE” label is treated as unsafe.
    * ``min_score_for_not_safe`` – threshold above which a non‑safe label is treated as safe.
    """

    @property
    @abstractmethod
    def pipeline_batch_size(self) -> int: ...

    @property
    @abstractmethod
    def min_score_for_safe(self) -> float: ...

    @property
    @abstractmethod
    def min_score_for_not_safe(self) -> float: ...
