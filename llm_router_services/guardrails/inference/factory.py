# guardrails/inference/factory.py
from __future__ import annotations

from typing import Any

from .base import GuardrailBase
from .text_classification import TextClassificationGuardrail, GenericModelConfig
from guardrails.inference.config import GuardrailModelConfig


def create(
    model_type: str,
    model_path: str,
    device: int = -1,
    *,
    config: GuardrailModelConfig | None = None,
    **kwargs: Any,
) -> GuardrailBase:
    """
    Factory that builds a concrete GuardrailBase implementation.

    Parameters
    ----------
    model_type:
        Identifier of the concrete implementation (e.g. ``"text_classification"``).
    model_path:
        Path or hub identifier of the model.
    device:
        ``-1`` → CPU, otherwise the CUDA device index.
    config:
        Optional model‑specific configuration object that implements
        :class:`GuardrailModelConfig`.  If omitted, a generic default config
        is used.
    kwargs:
        Additional arguments forwarded to the concrete class.
    """
    if model_type == "text_classification":
        # ``config`` may be ``None`` – the guardrail class will fall back to a
        # generic config.
        return TextClassificationGuardrail(
            model_path=model_path,
            device=device,
            config=config,
            **kwargs,
        )
    raise ValueError(f"Unsupported guardrail model_type: {model_type}")


# Public alias expected by the Flask app
GuardrailModelFactory = create
