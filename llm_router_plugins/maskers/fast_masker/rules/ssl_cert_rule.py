"""
Rule that masks SSL/TLS certificate serial numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import (
    is_valid_ssl_serial,
)


class SslCertRule(BaseRule):
    """
    Detects hex serial numbers (1‑64 hex chars) and masks them with
    ``{{SSL_CERT}}``.
    """

    # Match 16-40 hex characters (typical SSL cert serial range)
    _SSL_SERIAL_REGEX = r"""
        \b
        [0-9A-Fa-f]{16,40}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._SSL_SERIAL_REGEX,
            placeholder="{{SSL_CERT}}",
            flags=re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        def _replace(m: re.Match) -> str:
            return (
                self.placeholder if is_valid_ssl_serial(m.group(0)) else m.group(0)
            )

        return re.sub(self.pattern, _replace, text)
