"""
Anonymizer module
=================

Provides the :class:`Anonymizer` class – a thin orchestration layer that
applies a configurable sequence of
:class:`~llm_router_lib.anonymizer.core.rule_interface.AnonymizeRuleI`
implementations to arbitrary payloads.  The public API supports:

* Plain‑text anonymisation via :meth:`Anonymizer.anonymize`.
* Recursive anonymisation of complex data structures (``dict``, ``list`` and
  nested combinations) via :meth:`Anonymizer.anonymize_payload`.

The module imports the concrete rule classes (``PhoneRule``, ``UrlRule``, …) and
exposes a default rule set (``ALL_ANONYMIZER_RULES``) that can be overridden
by supplying a custom list to the constructor.
"""

from typing import List, Dict, Any, Optional

from llm_router_lib.anonymizer.core.rule_interface import AnonymizeRuleI

from llm_router_lib.anonymizer.rules import (
    PhoneRule,
    UrlRule,
    IpRule,
    PeselRule,
    EmailRule,
    NipRule,
    KrsRule,
    PostalCodeRule,
    MoneyRule,
    BankAccountRule,
    RegonRule,
)


class Anonymizer:
    """
    Orchestrates the application of a list of anonymisation rules.

    The class holds an ordered collection of objects implementing the
    :class:`AnonymizeRuleI` interface.  When processing input, each rule is
    invoked in the order provided, allowing later rules to operate on the
    output of earlier ones.  This deterministic ordering is important when
    rules might overlap (e.g., an e‑mail address that also looks like a URL).

    Attributes
    ----------
    rules : List[AnonymizeRuleI]
        The active rule set used by the instance.  If not supplied at
        construction time, the module‑level ``ALL_ANONYMIZER_RULES`` is used.
    """

    ALL_ANONYMIZER_RULES = [
        EmailRule(),
        UrlRule(),
        IpRule(),
        PeselRule(),
        NipRule(),
        KrsRule(),
        PostalCodeRule(),
        MoneyRule(),
        BankAccountRule(),
        RegonRule(),
        PhoneRule(),
    ]

    def __init__(self, rules: Optional[List[AnonymizeRuleI]] = None):
        """
        Initialise the anonymiser with an optional custom rule set.

        Parameters
        ----------
        rules : List[AnonymizeRuleI] | None
            An ordered collection of rule objects.  When ``None`` (the
            default), the class uses :data:`ALL_ANONYMIZER_RULES`.
        """
        self.rules = rules or self.ALL_ANONYMIZER_RULES

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
        return self._anonymize_text(text=text)

    def anonymize_payload(self, payload: Dict | str | List | Any):
        """
        Recursively anonymise a payload of arbitrary type.

        The method inspects the runtime type of *payload* and dispatches to
        the appropriate private helper:

        * ``str`` – treated as plain text and processed by
          :meth:`_anonymize_text`.
        * ``dict`` – each key and value is anonymised recursively via
          :meth:`_anonymize_dict`.
        * ``list`` – each element is anonymised recursively via
          :meth:`_anonymize_list`.
        * any other type – returned unchanged (no anonymisation needed).

        Parameters
        ----------
        payload : Union[Dict, str, List, Any]
            The data to be anonymised.

        Returns
        -------
        Union[Dict, str, List, Any]
            The anonymised representation of *payload*.
        """
        if type(payload) is str:
            return self._anonymize_text(text=payload)
        elif type(payload) is dict:
            return self._anonymize_dict(dict_payload=payload)
        elif type(payload) is list:
            return self._anonymize_list(list_payload=payload)
        return payload

    def _anonymize_text(self, text: str) -> str:
        """
        Apply all configured rules to a plain‑text string.

        The method iterates over :attr:`rules` in order, feeding the output of
        each rule back as the input to the next.  The final transformed string
        is returned.

        Parameters
        ----------
        text : str
            The original text to be anonymised.

        Returns
        -------
        str
            The fully anonymised text.
        """
        for rule in self.rules:
            text = rule.apply(text)
        return text

    def _anonymize_list(self, list_payload: List[Any]) -> List:
        """
        Anonymise each element of a list recursively.

        Elements may be of any type supported by :meth:`anonymize_payload`,
        including nested lists or dictionaries.

        Parameters
        ----------
        list_payload : List[Any]
            The list whose elements should be anonymised.

        Returns
        -------
        List[Any]
            A new list containing the anonymised elements.
        """
        _p = []
        for _e in list_payload:
            _p.append(self.anonymize_payload(payload=_e))
        return _p

    def _anonymize_dict(self, dict_payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """
        Anonymise the keys and values of a dictionary recursively.

        Both keys and values are passed through :meth:`anonymize_payload`,
        allowing complex nested structures (e.g., a dict whose keys are
        strings containing e‑mail addresses) to be fully processed.

        Parameters
        ----------
        dict_payload : Dict[Any, Any]
            The dictionary to be anonymised.

        Returns
        -------
        Dict[Any, Any]
            A new dictionary with anonymised keys and values.
        """
        _p = {}
        for k, v in dict_payload.items():
            _k = self.anonymize_payload(payload=k)
            _p[_k] = self.anonymize_payload(payload=v)
        return _p
