from llm_router_lib.tests.base import BaseEndpointTest


class PingTest(BaseEndpointTest):
    payload = None
    payload_model = None

    def client_method(self):
        return self._client.ping
