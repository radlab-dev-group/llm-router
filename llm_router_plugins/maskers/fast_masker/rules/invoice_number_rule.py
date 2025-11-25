"""
Rule that masks invoice numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class InvoiceNumberRule(BaseRule):
    """
    Detects typical invoice identifiers such as ``FV/2023/00123`` or
    ``INV-2023-456`` and masks them with ``{{INVOICE_NUMBER}}``.
    """

    _INVOICE_REGEX = r"""
        \b
        (?:FV|INV|INVOICE)[/\-]\d{4}[/\-]\d{3,6}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._INVOICE_REGEX,
            placeholder="{{INVOICE_NUMBER}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
