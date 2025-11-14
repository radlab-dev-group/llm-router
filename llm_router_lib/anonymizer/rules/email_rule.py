"""
Rule that anonymizes e‑mail addresses.
"""

import re
from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class EmailRule(BaseRule):
    """
    Detects e‑mail addresses and replaces them with ``{{EMAIL}}``.
    """

    # Simple e‑mail regex (local‑part + @ + domain). It is deliberately
    # permissive but avoids matching stray @ symbols inside words.
    _EMAIL_REGEX = r"""
        _?                     # optional leading underscore (markdown emphasis)
        [A-Za-z0-9._%+-]+      # local part
        @
        [A-Za-z0-9.-]+         # domain part
        \.[A-Za-z]{2,}         # TLD
        _?                     # optional trailing underscore (markdown emphasis)
    """

    def __init__(self):
        super().__init__(
            regex=self._EMAIL_REGEX,
            placeholder="{{EMAIL}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
