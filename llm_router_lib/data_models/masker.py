"""
Masker model definitions used by the ``MaskerPipeline``.

These lightweight Pydantic models describe the shape of data that a masker
plugin expects.  The actual masking logic lives in the pipeline implementation;
the models exist solely to provide type‑safe containers for the text payloads.
"""

from pydantic import BaseModel


class BaseMaskerModel(BaseModel):
    """
    Minimal container for text that should be anonymised or redacted.

    Attributes
    ----------
    text : str
        The raw text string that will be processed by a masker plugin.
    """

    text: str


class FastMaskerModel(BaseMaskerModel):
    """
    Simple concrete masker model.

    Inherits all fields from :class:`BaseMaskerModel` without adding new
    attributes.  It is used when the pipeline is configured for a fast,
    generic masking strategy.
    """

    ...


#
#
# class GenAIAnonymizerModel(BaseMaskerModel):
#     model_name: str
