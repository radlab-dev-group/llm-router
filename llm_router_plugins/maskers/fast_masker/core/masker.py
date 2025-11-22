"""
FastMasker module
=================

Provides the :class:`FastMasker` class – a thin orchestration layer that
applies a configurable sequence of
:class:`~llm_router_lib.fast_masker.core.rule_interface.MaskerRuleI`
implementations to arbitrary payloads.  The public API supports:

* Plain‑text masking via :meth:`FastMasker.mask_text`.
* Recursive masking of complex data structures (``dict``, ``list`` and
  nested combinations) via :meth:`FastMasker.mask_payload_fast`.

The module imports the concrete rule classes (``PhoneRule``, ``UrlRule``, …) and
exposes a default rule set (``ALL_MASKER_RULES``) that can be overridden
by supplying a custom list to the constructor.
"""

from typing import List, Dict, Any, Optional

from llm_router_lib.core.constants import USE_BETA_FEATURES

from llm_router_plugins.maskers.fast_masker.core.rule_interface import MaskerRuleI
from llm_router_plugins.maskers.fast_masker.rules import (
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
    DateNumberRule,
    DateWordRule,
)

if USE_BETA_FEATURES:
    from llm_router_plugins.maskers.fast_masker.rules import (
        StreetNameRule,
        SimplePersonalDataRule,
    )


class FastMasker:
    """
    Orchestrates the application of a list of simple masking rules.

    The class holds an ordered collection of objects implementing the
    :class:`MaskerRuleI` interface.  When processing input, each rule is
    invoked in the order provided, allowing later rules to operate on the
    output of earlier ones.  This deterministic ordering is important when
    rules might overlap (e.g., an e‑mail address that also looks like a URL).

    Attributes
    ----------
    rules : List[MaskerRuleI]
        The active rule set used by the instance.  If not supplied at
        construction time, the module‑level ``ALL_MASKER_RULES`` is used.
    """

    __ALL_MASKER_RULES = [
        EmailRule(),
        UrlRule(),
        IpRule(),
        StreetNameRule() if USE_BETA_FEATURES else None,
        PeselRule(),
        NipRule(),
        KrsRule(),
        PostalCodeRule(),
        MoneyRule(),
        BankAccountRule(),
        RegonRule(),
        DateWordRule(),
        DateNumberRule(),
        PhoneRule(),
        SimplePersonalDataRule() if USE_BETA_FEATURES else None,
    ]

    ALL_MASKER_RULES = [cls for cls in __ALL_MASKER_RULES if cls]

    def __init__(self, rules: Optional[List[MaskerRuleI]] = None):
        """
        Initialise the masker with an optional custom rule set.

        Parameters
        ----------
        rules : List[MaskerRuleI] | None
            An ordered collection of rule objects.  When ``None`` (the
            default), the class uses :data:`ALL_MASKER_RULES`.
        """
        self.rules = rules or self.ALL_MASKER_RULES

    def mask_text(self, text: str) -> str:
        """
        Run all configured rules over *text*.

        Parameters
        ----------
        text: str
            The original text.

        Returns
        -------
        str
            The fully masked text.
        """
        return self._mask_text(text=text)

    def mask_payload_fast(self, payload: Dict | str | List | Any):
        """
        Recursively mask a payload of arbitrary type.

        The method inspects the runtime type of *payload* and dispatches to
        the appropriate private helper:

        * ``str`` – treated as plain text and processed by
          :meth:`_mask_text`.
        * ``dict`` – each key and value is masked recursively via
          :meth:`_mask_dict`.
        * ``list`` – each element is masked recursively via
          :meth:`_mask_list`.
        * any other type – returned unchanged (no masking needed).

        Parameters
        ----------
        payload : Union[Dict, str, List, Any]
            The data to be masked.

        Returns
        -------
        Union[Dict, str, List, Any]
            The masked representation of *payload*.
        """
        if type(payload) is str:
            return self._mask_text(text=payload)
        elif type(payload) is dict:
            return self._mask_dict(dict_payload=payload)
        elif type(payload) is list:
            return self._mask_list(list_payload=payload)
        return payload

    def _mask_text(self, text: str) -> str:
        """
        Apply all configured rules to a plain‑text string.

        The method iterates over :attr:`rules` in order, feeding the output of
        each rule back as the input to the next.  The final transformed string
        is returned.

        Parameters
        ----------
        text : str
            The original text to be masked.

        Returns
        -------
        str
            The fully masked text.
        """
        for rule in self.rules:
            text = rule.apply(text)
        return text

    def _mask_list(self, list_payload: List[Any]) -> List:
        """
        Mask each element of a list recursively.

        Elements may be of any type supported by :meth:`mas_payload_fast`,
        including nested lists or dictionaries.

        Parameters
        ----------
        list_payload : List[Any]
            The list whose elements should be masked.

        Returns
        -------
        List[Any]
            A new list containing the masked elements.
        """
        _p = []
        for _e in list_payload:
            _p.append(self.mask_payload_fast(payload=_e))
        return _p

    def _mask_dict(self, dict_payload: Dict[Any, Any]) -> Dict[Any, Any]:
        """
        Maske the keys and values of a dictionary recursively.

        Both keys and values are passed through :meth:`mask_payload_fast`,
        allowing complex nested structures (e.g., a dict whose keys are
        strings containing e‑mail addresses) to be fully processed.

        Parameters
        ----------
        dict_payload : Dict[Any, Any]
            The dictionary to be masked.

        Returns
        -------
        Dict[Any, Any]
            A new dictionary with masked keys and values.
        """
        _p = {}
        for k, v in dict_payload.items():
            _k = self.mask_payload_fast(payload=k)
            _p[_k] = self.mask_payload_fast(payload=v)
        return _p
