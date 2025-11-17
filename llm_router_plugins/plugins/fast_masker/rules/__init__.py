"""
Package that contains concrete masking rule implementations.
"""

from llm_router_lib.core.constants import USE_BETA_FEATURES

from llm_router_plugins.plugins.fast_masker.rules.ip_rule import IpRule
from llm_router_plugins.plugins.fast_masker.rules.url_rule import UrlRule
from llm_router_plugins.plugins.fast_masker.rules.phone_rule import PhoneRule
from llm_router_plugins.plugins.fast_masker.rules.pesel_rule import PeselRule
from llm_router_plugins.plugins.fast_masker.rules.email_rule import EmailRule
from llm_router_plugins.plugins.fast_masker.rules.krs_rule import KrsRule
from llm_router_plugins.plugins.fast_masker.rules.nip_rule import NipRule
from llm_router_plugins.plugins.fast_masker.rules.money_rule import MoneyRule
from llm_router_plugins.plugins.fast_masker.rules.postal_code_rule import (
    PostalCodeRule,
)
from llm_router_plugins.plugins.fast_masker.rules.bank_account_rule import (
    BankAccountRule,
)
from llm_router_plugins.plugins.fast_masker.rules.date_number_rule import (
    DateNumberRule,
)
from llm_router_plugins.plugins.fast_masker.rules.date_word_rule import DateWordRule
from llm_router_plugins.plugins.fast_masker.rules.regon_rule import RegonRule


if USE_BETA_FEATURES:
    from llm_router_plugins.plugins.fast_masker.rules.beta.street_rule import (
        StreetNameRule,
    )
    from llm_router_plugins.plugins.fast_masker.rules.beta.personal_data import (
        SimplePersonalDataRule,
    )
