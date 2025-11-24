# guardrails/nask/config.py
from __future__ import annotations

from dataclasses import dataclass

from guardrails.inference.config import GuardrailModelConfig


# -----------------------------------------------------------------------
# NASK‑PIB specific configuration – implements the GuardrailModelConfig
# interface.  These values were previously hard‑coded inside the processor.
# -----------------------------------------------------------------------
@dataclass(frozen=True)
class NaskModelConfig(GuardrailModelConfig):
    pipeline_batch_size: int = 64
    min_score_for_safe: float = 0.5
    min_score_for_not_safe: float = 0.5
