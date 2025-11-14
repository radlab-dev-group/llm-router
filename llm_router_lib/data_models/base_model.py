"""
Base model definitions for the LLM router library.

This module contains lightweight Pydantic models that encapsulate common
configuration options shared across multiple components.  Currently, it defines
a single ``BaseModelOptions`` class with a boolean flag that indicates whether
the request payload should be anonymised before further processing.
"""

from pydantic import BaseModel


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
    """

    anonymize: bool = False
