from typing import Optional, Dict, Any

from llm_proxy_rest.endpoints.endpoint_i import EndpointI


class Ping(EndpointI):
    """
    Health‑check endpoint that returns a simple *pong* response.

    This endpoint is registered under the name ``ping`` and only supports
    the HTTP ``GET`` method.  It does not require any request parameters
    and is typically used by monitoring tools to verify that the service
    is up and responding.

    Attributes:
        REQUIRED_ARGS (list): Empty list – no required arguments.
        OPTIONAL_ARGS (list): Empty list – no optional arguments.
    """

    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []

    def __init__(self):
        """
        Create a ``Ping`` endpoint instance.

        Calls the base ``EndpointI`` initializer with
        the appropriate HTTP method and endpoint name.
        """
        super().__init__(method="GET", ep_name="ping")

    def call(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Execute the endpoint logic.

        Args:
            params: Optional dictionary of query parameters.
                The ping endpoint ignores any supplied parameters.

        Returns:
            dict: A response dictionary containing the string ``"pong"``,
            generated via ``return_response_ok``.
        """
        return self.return_response_ok("pong")
