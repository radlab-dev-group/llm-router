"""
Definition of the rule interface that every anonymization rule must implement.
"""

from abc import ABC, abstractmethod


class AnonymizeRuleI(ABC):
    """
    Abstract base class for all anonymization rules.

    Sub‑classes must implement the :meth:`apply` method, which receives a
    string and returns a new string where the rule‑specific patterns have been
    replaced with placeholders.
    """

    @abstractmethod
    def apply(self, text: str) -> str:
        """
        Apply the rule to *text* and return the transformed string.

        Parameters
        ----------
        text: str
            The input text to be processed.

        Returns
        -------
        str
            The text after the rule has been applied.
        """
        raise NotImplementedError
