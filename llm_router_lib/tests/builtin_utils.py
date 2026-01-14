from llm_router_lib.data_models.builtin_utils import TranslateTextModel

from llm_router_lib.tests.base import BaseEndpointTest


class TranslateTextModelTest(BaseEndpointTest):
    payload = {
        "model_name": "google/gemma-3-12b-it",
        "texts": [
            "Jesień przeplatała się kolorami pomarańczowymi z czerwienią!",
            "Białe buty zawsze szybko się brudzą!",
            "Tęcza ma wszelakie kolory! A białego nie ma?!",
        ],
    }
    payload_model = TranslateTextModel

    def client_method(self):
        return self._client.translate
