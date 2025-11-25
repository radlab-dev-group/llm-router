"""
Rule that masks international phone numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class PhoneInternationalRule(BaseRule):
    """
    Detects phone numbers that start with a leading ``+`` followed by country code
    and subscriber number (e.g. ``+48 123 456 789``) and masks them with
    ``{{PHONE_INTERNATIONAL}}``.
    """

    _PHONE_INTL_REGEX = r"""
        \b
        \+                     # leading plus
        \d{1,3}                # country code (1‑3 digits)
        (?:[ \-]?\d{1,4}){2,5} # groups of digits separated by space or dash
        \b
    """

    def __init__(self):
        super().__init__(
            regex=self._PHONE_INTL_REGEX,
            placeholder="{{PHONE_INTERNATIONAL}}",
            flags=re.VERBOSE,
        )
