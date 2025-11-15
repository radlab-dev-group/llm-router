"""
Rule that mask IPv4 and IPv6 addresses.
"""

import re

from llm_router_plugins.plugins.fast_masker.rules.base_rule import BaseRule


class IpRule(BaseRule):
    """
    Detects IPv4, IPv6 addresses **and** the special hostname ``localhost``.
    If a port is present after a colon (e.g. ``localhost:1211`` or
    ``0.0.0.0:2131``) the address and the port are masked **separately**,
    yielding ``{{IP}}:{{PORT}}``.
    """

    # Placeholder for the IP/hostname part
    _IP_PLACEHOLDER = "{{IP}}"
    # Placeholder for the port part (if any)
    _PORT_PLACEHOLDER = "{{PORT}}"

    # IPv4: four octets, each 0‑255 (light validation, not strict)
    _IPv4_REGEX = r"""
        (?:\d{1,3}\.){3}\d{1,3}
    """

    # IPv6: eight groups of 1‑4 hex digits separated by ':'
    _IPv6_REGEX = r"""
        (?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}
    """

    # Hostname we want to treat as an IP address
    _LOCALHOST_REGEX = r"localhost"

    # Combined address regex (IPv4 | IPv6 | localhost)
    _ADDRESS_REGEX = rf"""
        (?P<addr>
            {_LOCALHOST_REGEX}
            |
            {_IPv4_REGEX}
            |
            {_IPv6_REGEX}
        )
    """

    # Optional port (digits after a colon)
    _PORT_REGEX = r"""
        (?:\:(?P<port>\d{1,5}))?
    """

    # Full pattern: address optionally followed by a port
    _IP_REGEX = rf"""
        \b
        {_ADDRESS_REGEX}
        {_PORT_REGEX}
        \b
    """

    def __init__(self):
        super().__init__(
            regex=self._IP_REGEX,
            placeholder=self._IP_PLACEHOLDER,
            flags=re.VERBOSE,
        )
        # Compile the pattern for direct use in ``apply``.
        self._compiled_regex = re.compile(self._IP_REGEX, flags=re.VERBOSE)

    def apply(self, text: str) -> str:
        """
        Replace each address with ``{{IP}}`` and, if a port is present,
        replace it with ``{{PORT}}`` while preserving the separating colon.
        """

        def replacer(match: re.Match) -> str:
            # Always replace the address part
            result = self._IP_PLACEHOLDER
            # If a port was captured, append ``:{{PORT}}``
            if match.group("port"):
                result = f"{result}:{self._PORT_PLACEHOLDER}"
            return result

        return self._compiled_regex.sub(replacer, text)
