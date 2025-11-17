"""
Base model definitions for the LLM router library.

This module contains lightweight Pydantic models that encapsulate common
configuration options shared across multiple components.  Currently, it defines
a single ``BaseModelOptions`` class with a boolean flag that indicates whether
the request payload should be anonymised before further processing.
"""

from pydantic import BaseModel
from typing import Literal, Optional


class BaseModelOptions(BaseModel):
    """
    Configuration options applicable to various request‑handling models.

    Attributes
    ----------
    anonymize : bool, default ``False``
        When set to ``True`` the incoming payload will be passed through the
        library's :class:`~llm_router_lib.anonymizer.core.Anonymizer` before any
        downstream logic is executed.  The default value ``False`` disables
        anonymisation.

    anonymize_algorithm : Literal["fast_masker", "genai", "priv_masker"], default ``"fast_masker"``
        Specifies which anonymisation algorithm to use when ``anonymize`` is ``True``.
        * ``"fast_masker"`` – a lightweight, high‑performance masker.
        * ``"genai"`` – a generative‑AI based approach.
        * ``"priv_masker"`` – a privacy‑focused masking technique.

    model_name_anonymize : Optional[str], default ``None``
        Name or identifier of the model to be used for anonymisation when
        ``anonymize_algorithm`` requires a specific model (e.g., for the ``"genai"``
        algorithm).  If ``None``, the library will fall back to its default model.
    """

    anonymize: bool = False
    anonymize_algorithm: Literal["fast_masker", "genai", "priv_masker"] = (
        "fast_masker"
    )
    model_name_anonymize: Optional[str] = None
