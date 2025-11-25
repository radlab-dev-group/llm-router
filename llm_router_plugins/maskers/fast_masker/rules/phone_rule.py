"""
Rule that masks phone numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class PhoneRule(BaseRule):
    """
    Detects common phone number formats and replaces them with ``{{PHONE}}``.
    """

    # Polish phone numbers: 9 digits with optional spaces/dashes
    # Examples: 123 456 789, 123-456-789, 123456789
    _PHONE_REGEX = r"""
        \b
        (?:
            (?:\d{3}[\s-]?\d{3}[\s-]?\d{3})   # 123 456 789 or 123-456-789
            |
            (?:\d{2}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2})   # 12 345 67 89
        )
        \b
    """

    def __init__(self):
        super().__init__(
            regex=self._PHONE_REGEX, placeholder="{{PHONE}}", flags=re.VERBOSE
        )
