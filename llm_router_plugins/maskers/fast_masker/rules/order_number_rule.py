"""
Rule that masks order numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class OrderNumberRule(BaseRule):
    """
    Detects e‑commerce order identifiers like ``ORD123456`` or
    ``ORDER-2023-001`` and masks them with ``{{ORDER_NUMBER}}``.
    """

    _ORDER_REGEX = r"""
        \b
        (?:ORD|ORDER)[\-_]?\d{3,10}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._ORDER_REGEX,
            placeholder="{{ORDER_NUMBER}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
