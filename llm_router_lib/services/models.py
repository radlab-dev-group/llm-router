from llm_router_lib.services.service_interface import (
    BaseConversationServiceInterface,
)


class AllModelsService(BaseConversationServiceInterface):
    endpoint = "/v1/models"
    model_cls = None
