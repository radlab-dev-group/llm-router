"""
Rule that masks phone numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class PhoneRule(BaseRule):
    """
    Detects common phone number formats and replaces them with ``{{PHONE}}``.
    """

    # Very permissive pattern that matches:
    # +48 123 456 789, 123-456-789, (123) 456 7890, 1234567890, etc.
    _PHONE_REGEX = r"""
        (?:
            \+?\d{1,3}[\s-]?          # optional country code
        )?
        (?:\(?\d{2,4}\)?[\s-]?)?      # optional area code
        \d{3}[\s-]?\d{2,4}[\s-]?\d{2,4}   # main number blocks
    """

    def __init__(self):
        super().__init__(
            regex=self._PHONE_REGEX, placeholder="{{PHONE}}", flags=re.VERBOSE
        )
