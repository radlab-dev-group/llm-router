"""
Rule that masks Vehicle Identification Numbers (VIN).
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import is_valid_vin


class VinRule(BaseRule):
    """
    Detects 17‑character VINs and masks them with ``{{VIN}}`` **only if the
    checksum (position 9) is correct**.
    """

    _VIN_REGEX = r"""
        \b
        [A-HJ-NPR-Z0-9]{17}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._VIN_REGEX,
            placeholder="{{VIN}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        def _replace(m: re.Match) -> str:
            vin = m.group(0)
            return self.placeholder if is_valid_vin(vin) else vin

        return re.sub(self.pattern, _replace, text)
