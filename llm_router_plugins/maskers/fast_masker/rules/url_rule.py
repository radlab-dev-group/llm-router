import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class UrlRule(BaseRule):
    """
    Detects HTTP/HTTPS URLs **and** plain domain names (e.g. www.wp.pl,
    radlab.dev) and replaces them with ``{{URL}}``.
    """

    # The pattern matches:
    #   • Full URLs with http:// or https:// scheme
    #   • OR standalone domains (www.example.com) that are NOT part of code
    # Avoids matching code patterns like: requests.post, response.json, object.method
    _URL_REGEX = r"""
        (?:
            # Option 1: Full URL with scheme (always match)
            \b(?:https?://)
            (?:[A-Za-z0-9-]+\.)*         # optional subdomains
            [A-Za-z0-9-]+                # domain name
            \.                           # dot
            [A-Za-z]{2,}                 # TLD
            (?:[/:][^\s\)]*)?            # optional path (stop at closing paren)
        |
            # Option 2: Domain without scheme (only if not preceded by identifier)
            (?<![A-Za-z0-9_])            # NOT preceded by identifier char
            (?:www\.|[A-Za-z0-9-]+\.)    # must start with www. or subdomain.
            [A-Za-z0-9-]+                # domain name
            \.                           # dot
            (?:com|org|net|edu|gov|pl|dev|io|co|uk|de|fr|it|es|ru|cn|jp|br|au|in|nl|se|no|fi|dk|cz|sk|eu|info|biz)  # common TLDs
            \b
            (?![A-Za-z0-9_\(])           # NOT followed by identifier or (
        )
    """

    def __init__(self):
        super().__init__(
            regex=self._URL_REGEX,
            placeholder="{{URL}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )
