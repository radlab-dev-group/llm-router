from llm_router_lib.services.service_interface import (
    BaseConversationServiceInterface,
)


class PingService(BaseConversationServiceInterface):
    endpoint = "/api/ping"
    model_cls = None
