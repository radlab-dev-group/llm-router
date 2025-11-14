"""
The main orchestrator that applies a list of rules sequentially.
"""

from typing import List

from llm_router_lib.anonymizer.core.rule_interface import AnonymizeRuleI


class Anonymizer:
    """
    Apply a series of :class:`AnonymizeRuleI` implementations to a piece of text.

    The rules are applied in the order they appear in the *rules* list.
    """

    def __init__(self, rules: List[AnonymizeRuleI]):
        """
        Parameters
        ----------
        rules: List[AnonymizeRuleI]
            Ordered collection of rule objects.
        """
        self.rules = rules

    def anonymize(self, text: str) -> str:
        """
        Run all configured rules over *text*.

        Parameters
        ----------
        text: str
            The original text.

        Returns
        -------
        str
            The fully anonymized text.
        """
        for rule in self.rules:
            text = rule.apply(text)
        return text
