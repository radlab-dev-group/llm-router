import abc
import json

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
        print(f"Running {self.client_method}")
        if self.payload:
            print("- " * 50)
            print(" =========== payload =========== ")
            print(json.dumps(self.payload, indent=2, ensure_ascii=False))

            _p = self.payload.copy()
            _p["model_name"] = model_name
            return self.client_method()(payload=self.payload_model(**_p))
        return self.client_method()()
