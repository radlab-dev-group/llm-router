"""
Rule that masks generic transaction reference strings.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import (
    is_possible_transaction_ref,
)


class TransactionRefRule(BaseRule):
    """
    Detects strings that look like transaction IDs (e.g. ``TRX-20231125-001``)
    and masks them with ``{{TRANSACTION_REF}}``.
    """

    _TRANS_REF_REGEX = r"""
        \b
        [A-Z]{2,5}[-_]\d{4,8}[-_]\d{3,6}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._TRANS_REF_REGEX,
            placeholder="{{TRANSACTION_REF}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        def _replace(m: re.Match) -> str:
            ref = m.group(0)
            return self.placeholder if is_possible_transaction_ref(ref) else ref

        return re.sub(self.pattern, _replace, text)
