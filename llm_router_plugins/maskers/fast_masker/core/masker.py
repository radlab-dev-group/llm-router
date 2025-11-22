"""
FastMasker module
=================

Provides the :class:`FastMasker` class – a thin orchestration layer that
applies a configurable sequence of
:class:`~llm_router_lib.fast_masker.core.rule_interface.MaskerRuleI`
implementations to arbitrary payloads.

The module imports the concrete rule classes (``PhoneRule``, ``UrlRule``, …) and
exposes a default rule set (``ALL_MASKER_RULES``) that can be overridden
by supplying a custom list to the constructor.
"""

from typing import List, Optional

from llm_router_lib.core.constants import USE_BETA_FEATURES

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
from llm_router_plugins.maskers.payload_interface import MaskerPayloadTraveler
from llm_router_plugins.maskers.fast_masker.core.rule_interface import MaskerRuleI

if USE_BETA_FEATURES:
    from llm_router_plugins.maskers.fast_masker.rules import (
        StreetNameRule,
        SimplePersonalDataRule,
    )


class FastMasker(MaskerPayloadTraveler):
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
