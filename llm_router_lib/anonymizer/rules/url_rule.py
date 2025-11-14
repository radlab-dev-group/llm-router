"""
Rule that anonymizes web URLs.
"""

import re

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class UrlRule(BaseRule):
    """
    Detects HTTP/HTTPS URLs and replaces them with ``{{URL}}``.
    """

    _URL_REGEX = r"""
        \b
        https?://               # http or https scheme
        [^\s/$.?#].[^\s]*       # domain + optional path/query
    """

    def __init__(self):
        super().__init__(
            regex=self._URL_REGEX,
            placeholder="{{URL}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
