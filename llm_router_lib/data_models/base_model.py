"""
Base model definitions for the LLM router library.

This module contains lightweight Pydantic models that encapsulate common
configuration options shared across multiple components.  Currently, it defines
a single ``BaseModelOptions`` class with a boolean flag that indicates whether
the request payload should be anonymised before further processing.
"""

from pydantic import BaseModel
from typing import Optional, List


class BaseModelOptions(BaseModel):
    """
    Configuration options applicable to various request‑handling models.

    Attributes
    ----------

    mask_payload: bool, Default False, Whether to mask the payload before
    sending it to the LLM provider.

    masker_pipeline : Pipeline of maskers, list with names of plugins
    used as a pipeline to mask payload
    """

    mask_payload: bool = False
    masker_pipeline: Optional[List[str]] = None
