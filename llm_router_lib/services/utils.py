from llm_router_lib.data_models.builtin_utils import TranslateTextModel
from llm_router_lib.services.conversation import BaseConversationServiceInterface


class TranslateTextService(BaseConversationServiceInterface):
    endpoint = "/api/translate"
    model_cls = TranslateTextModel
