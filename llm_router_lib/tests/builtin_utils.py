from llm_router_lib.data_models.builtin_utils import (
    Polarity3cModel,
    TranslateTextModel,
)

from llm_router_lib.tests.base import BaseEndpointTest


class Polarity3cModelTest(BaseEndpointTest):
    payload = {
        "model_name": "google/gemma-3-12b-it",
        "language": "pl",
        "texts": [
            "To jest niesamowity, wspaniały produkt! Bardzo polecam!",
            "Totalna katastrofa, nie polecam nikomu, produkt zepsuty.",
            "Produkt spełnia podstawowe wymagania, "
            "ale niczym szczególnym się nie wyróżnia.",
        ],
        "temperature": 0.0,
    }
    payload_model = Polarity3cModel

    def client_method(self):
        return self._client.polarity_3c


class TranslateTextModelTest(BaseEndpointTest):
    payload = {
        "model_name": "google/gemma-3-12b-it",
        "language": "pl",
        "texts": [
            "Jesień przeplatała się kolorami pomarańczowymi z czerwienią!",
            "Białe buty zawsze szybko się brudzą!",
            "Tęcza ma wszelakie kolory! A białego nie ma?!",
        ],
        "temperature": 0.2,
    }
    payload_model = TranslateTextModel

    def client_method(self):
        return self._client.translate
