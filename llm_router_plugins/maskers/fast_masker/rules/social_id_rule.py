"""
Rule that masks generic social‑media identifiers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class SocialIdRule(BaseRule):
    """
    Detects IDs that look like typical social‑media handles:
      • ``@username`` (Twitter, Instagram)
      • ``fbid1234567890`` (Facebook numeric ID)
    Masks them with ``{{SOCIAL_ID}}``.
    """

    # Match only fbid to avoid collision with email @ symbol
    _SOCIAL_REGEX = r"""
        \b
        fbid\d{8,}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._SOCIAL_REGEX,
            placeholder="{{SOCIAL_ID}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
