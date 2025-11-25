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


from llm_router_plugins.maskers.fast_masker.rules import *
from llm_router_plugins.maskers.payload_interface import MaskerPayloadTraveler
from llm_router_plugins.maskers.fast_masker.core.rule_interface import MaskerRuleI


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

    # Rules ordered from most specific/certain to least specific
    # Priority: checksum-validated > structured formats > pattern-based
    __ALL_MASKER_RULES = [
        # 1. HIGHEST CERTAINTY - Checksum validated identifiers
        CreditCardRule(),  # Luhn checksum
        VinRule(),  # VIN checksum (ISO 3779)
        PeselTaggedRule(),  # PESEL with label + checksum
        PeselRule(),  # PESEL with checksum
        NipRule(),  # NIP with checksum
        KrsRule(),  # KRS with checksum
        RegonRule(),  # REGON with checksum
        # 2. HIGH CERTAINTY - Strict formats with validation
        NrbRule(),  # 26 digits (bank account)
        MacAddressRule(),  # MAC address format
        PassportRule(),  # 2 letters + 7 digits
        IdCardRule(),  # 3 letters + 6 digits
        SsnRule(),  # SSN format AAA-GG-SSSS
        # EuVatRule(),             # EU VAT - disabled (too noisy, catches words like "Configuration")
        # 3. MEDIUM-HIGH - International phone numbers (more specific than local)
        PhoneInternationalRule(),  # + prefix with country code
        # 4. MEDIUM - Well-structured formats
        EmailRule(),  # Email addresses (before URLs!)
        UrlRule(),  # URLs and domains
        IpRule(),  # IP addresses with optional ports
        BankAccountRule(),  # Polish IBAN
        # 5. MEDIUM-LOW - Business identifiers with structure
        JwtRule(),  # JWT tokens (3 parts)
        InvoiceNumberRule(),  # FV/INV patterns
        OrderNumberRule(),  # ORD patterns
        TransactionRefRule(),  # Transaction IDs
        # 6. LOWER CERTAINTY - Pattern-based with context
        DateWordRule(),  # Textual dates
        DateNumberRule(),  # Numeric dates
        MoneyRule(),  # Amounts with currency
        # 7. FORMAT-BASED - Specific patterns
        PostalCodeRule(),  # DD-DDD format
        HealthIdRule(),  # NFZ with slash
        CarPlateRule(),  # License plates
        SimCardRule(),  # 19-20 digit ICCID
        SslCertRule(),  # 16-40 hex chars
        # 8. LOWEST CERTAINTY - Generic patterns (potentially noisy)
        StreetNameRule(),  # Street
        PhoneRule(),  # Local phone (9 digits)
        SocialIdRule(),  # fbid only
        # Beta features (if enabled)
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
