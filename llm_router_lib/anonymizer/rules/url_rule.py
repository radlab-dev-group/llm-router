"""
Rule that anonymizes web URLs.
"""

import re

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class UrlRule(BaseRule):
    """
    Detects HTTP/HTTPS URLs **and** plain domain names (e.g. www.wp.pl,
    radlab.dev) and replaces them with ``{{URL}}``.
    """

    # The pattern matches:
    #   • An optional scheme (http:// or https://)
    #   • One or more sub‑domains/labels ending with a dot
    #   • A top‑level domain of at least two letters (covers .pl, .dev, etc.)
    #   • An optional path, query string or fragment starting with '/' or ':'
    # It works for full URLs like ``https://example.com/path`` and for
    # plain domains such as ``www.wp.pl`` or ``radlab.dev``.
    _URL_REGEX = r"""
        \b
        (?:https?://)?               # optional http/https scheme
        (?:[A-Za-z0-9-]+\.)+         # one or more sub‑domains / domain labels
        [A-Za-z]{2,}                 # top‑level domain (at least 2 letters)
        (?:[/:][^\s]*)?              # optional path, query or fragment
    """

    def __init__(self):
        super().__init__(
            regex=self._URL_REGEX,
            placeholder="{{URL}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
