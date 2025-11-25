"""
Rule that masks Polish national ID card numbers (9‑character alphanumeric).
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class IdCardRule(BaseRule):
    """
    Detects Polish ID‑card numbers – three letters followed by six digits
    (e.g. ``ABC123456``) – and masks them with ``{{ID_CARD}}``.
    """

    _ID_REGEX = r"""
        \b
        [A-Z]{3}\d{6}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._ID_REGEX,
            placeholder="{{ID_CARD}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
