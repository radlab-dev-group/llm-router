"""
Rule that masks passport numbers (9‑character alphanumeric).
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class PassportRule(BaseRule):
    """
    Detects typical passport numbers – two letters followed by seven digits
    (e.g. ``AB1234567``) – and masks them with ``{{PASSPORT}}``.
    """

    _PASSPORT_REGEX = r"""
        \b
        [A-Z]{2}\d{7}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._PASSPORT_REGEX,
            placeholder="{{PASSPORT}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
