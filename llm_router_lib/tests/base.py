import abc

from llm_router_lib import LLMRouterClient


class BaseEndpointTest(abc.ABC):
    payload = None
    payload_model = None

    def __init__(self, client: LLMRouterClient):
        self._client = client

    @abc.abstractmethod
    def client_method(self):
        pass

    def run(self, model_name):
        if self.payload:
            _p = self.payload.copy()
            _p["model_name"] = model_name
            return self.client_method()(payload=self.payload_model(**_p))
        return self.client_method()()
