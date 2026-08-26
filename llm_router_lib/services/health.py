from llm_router_lib.services.service_interface import (
    BaseConversationServiceInterface,
)


class PingService(BaseConversationServiceInterface):
    """
    Service wrapper for the health‑check ``/api/ping`` endpoint.

    This endpoint is typically used to verify that the router service is
    reachable and operational.  It performs a simple ``GET`` request and
    returns the JSON payload provided by the backend (commonly something like
    ``{\"status\": \"ok\"}``).

    Attributes
    ----------
    endpoint : str
        The relative URL of the ping endpoint (``"/api/ping"``).
    model_cls : None
        No request payload model is required for this endpoint.
    """

    endpoint = "/api/ping"
    model_cls = None


class VersionService(BaseConversationServiceInterface):
    """
    Service wrapper for the ``/api/version`` endpoint.

    Retrieves version information about the running router instance.  The
    endpoint returns a JSON object containing fields such as ``version``,
    ``commit_hash`` or any other metadata the service chooses to expose.

    Attributes
    ----------
    endpoint : str
        The relative URL of the version endpoint (``"/api/version"``).
    model_cls : None
        No request payload model is required for this endpoint.
    """

    endpoint = "/api/version"
    model_cls = None


class ModelsService(BaseConversationServiceInterface):
    """
    Service wrapper for the ``/v1/models`` endpoint.

    Retrieves the list of models currently available on the router.  The
    endpoint returns an OpenAI‑compatible payload::

        {"object": "list", "data": [{"id", "object", "created", "owned_by"}, ...]}

    Attributes
    ----------
    endpoint : str
        The relative URL of the list of models endpoint (``"/v1/models"``).
    model_cls : None
        No request payload model is required for this endpoint.
    """

    endpoint = "/v1/models"
    model_cls = None
