"""
Package that contains concrete masking rule implementations.
"""

from llm_router_lib.core.constants import USE_BETA_FEATURES

if USE_BETA_FEATURES:
    from llm_router_plugins.maskers.fast_masker.rules.beta.personal_data import (
        SimplePersonalDataRule,
    )

from llm_router_plugins.maskers.fast_masker.rules.beta.street_rule import (
    StreetNameRule,
)
from llm_router_plugins.maskers.fast_masker.rules.credit_card_rule import (
    CreditCardRule,
)
from llm_router_plugins.maskers.fast_masker.rules.nrb_rule import NrbRule
from llm_router_plugins.maskers.fast_masker.rules.vin_rule import VinRule
from llm_router_plugins.maskers.fast_masker.rules.mac_address_rule import (
    MacAddressRule,
)
from llm_router_plugins.maskers.fast_masker.rules.jwt_rule import JwtRule
from llm_router_plugins.maskers.fast_masker.rules.sim_card_rule import SimCardRule
from llm_router_plugins.maskers.fast_masker.rules.ssl_cert_rule import SslCertRule
from llm_router_plugins.maskers.fast_masker.rules.transaction_ref_rule import (
    TransactionRefRule,
)
from llm_router_plugins.maskers.fast_masker.rules.invoice_number_rule import (
    InvoiceNumberRule,
)
from llm_router_plugins.maskers.fast_masker.rules.order_number_rule import (
    OrderNumberRule,
)
from llm_router_plugins.maskers.fast_masker.rules.car_plate_rule import CarPlateRule
from llm_router_plugins.maskers.fast_masker.rules.health_id_rule import HealthIdRule
from llm_router_plugins.maskers.fast_masker.rules.id_card_rule import IdCardRule
from llm_router_plugins.maskers.fast_masker.rules.passport_rule import PassportRule
from llm_router_plugins.maskers.fast_masker.rules.pesel_tagged_rule import (
    PeselTaggedRule,
)
from llm_router_plugins.maskers.fast_masker.rules.pesel_rule import PeselRule
from llm_router_plugins.maskers.fast_masker.rules.phone_international_rule import (
    PhoneInternationalRule,
)
from llm_router_plugins.maskers.fast_masker.rules.phone_rule import PhoneRule
from llm_router_plugins.maskers.fast_masker.rules.email_rule import EmailRule
from llm_router_plugins.maskers.fast_masker.rules.url_rule import UrlRule
from llm_router_plugins.maskers.fast_masker.rules.ip_rule import IpRule
from llm_router_plugins.maskers.fast_masker.rules.bank_account_rule import (
    BankAccountRule,
)
from llm_router_plugins.maskers.fast_masker.rules.date_number_rule import (
    DateNumberRule,
)
from llm_router_plugins.maskers.fast_masker.rules.date_word_rule import DateWordRule
from llm_router_plugins.maskers.fast_masker.rules.krs_rule import KrsRule
from llm_router_plugins.maskers.fast_masker.rules.money_rule import MoneyRule
from llm_router_plugins.maskers.fast_masker.rules.nip_rule import NipRule
from llm_router_plugins.maskers.fast_masker.rules.postal_code_rule import (
    PostalCodeRule,
)
from llm_router_plugins.maskers.fast_masker.rules.regon_rule import RegonRule
from llm_router_plugins.maskers.fast_masker.rules.social_id_rule import SocialIdRule
from llm_router_plugins.maskers.fast_masker.rules.ssn_rule import SsnRule
from llm_router_plugins.maskers.fast_masker.rules.eu_vat_rule import EuVatRule
