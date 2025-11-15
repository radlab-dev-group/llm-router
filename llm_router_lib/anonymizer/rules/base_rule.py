"""
Optional helper base class for rules that share common behaviour.
"""

import abc
import re
from typing import Pattern

from llm_router_lib.anonymizer.core.rule_interface import AnonymizeRuleI


class BaseRule(AnonymizeRuleI, abc.ABC):
    """
    Simple base class that stores a compiled regular expression and a
    replacement placeholder. Sub‑classes only need to provide the pattern
    and placeholder.
    """

    pattern: Pattern
    placeholder: str

    def __init__(self, regex: str, placeholder: str, flags: int = 0):
        """
        Parameters
        ----------
        regex: str
            Regular expression pattern to search for.
        placeholder: str
            Text that will replace each match.
        flags: int, optional
            Flags passed to :func:`re.compile`. Default is ``0``.
        """
        self.pattern = re.compile(regex, flags)
        self.placeholder = placeholder

    def apply(self, text: str) -> str:
        """
        Replace all occurrences of ``self.pattern`` in *text* with the
        configured placeholder.

        Returns
        -------
        str
            The transformed text.
        """
        return self.pattern.sub(self.placeholder, text)
