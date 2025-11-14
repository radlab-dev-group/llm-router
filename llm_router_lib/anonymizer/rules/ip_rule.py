"""
Rule that anonymizes IPv4 and IPv6 addresses.
"""

import re

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class IpRule(BaseRule):
    """
    Detects IPv4 and IPv6 addresses and replaces them with ``{{IP}}``.
    """

    # IPv4: four octets, each 0‑255 (light validation, not strict)
    _IPv4_REGEX = r"""
        \b
        (?:\d{1,3}\.){3}\d{1,3}
        \b
    """

    # IPv6: eight groups of 1‑4 hex digits separated by ':'
    _IPv6_REGEX = r"""
        \b
        (?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}
        \b
    """

    # Combine both with a non‑capturing alternation
    _IP_REGEX = rf"(?:{_IPv4_REGEX})|(?:{_IPv6_REGEX})"

    def __init__(self):
        super().__init__(
            regex=self._IP_REGEX, placeholder="{{IP}}", flags=re.VERBOSE
        )
