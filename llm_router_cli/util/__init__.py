"""
Utility apps for the ``llm-router`` CLI (ported from ``llm-router-utils``).

This sub-package contains self-contained, dependency-light implementations of
the three utility applications:

* :class:`llm_router_cli.util.translate.TranslateApp`
* :class:`llm_router_cli.util.genai_classifier.GenAIClassifierApp`
* :class:`llm_router_cli.util.genai_data_augmentation.GenAIDataAugmentationApp`

They are intentionally kept **light**: only local JSON/JSONL files are read,
there is **no** HuggingFace ``datasets`` / ``pandas`` / ``openpyxl`` /
``tenacity`` import anywhere in this package, and retries are handled by a
tiny in-repo helper (:func:`llm_router_cli.util.retry.with_retries`) plus the
``LLMRouterClient``'s own built-in network retries.
"""

from __future__ import annotations

__all__ = [
    "loaders",
    "retry",
    "translate",
    "genai_classifier",
    "genai_data_augmentation",
]

__version__ = "1.0.0"
