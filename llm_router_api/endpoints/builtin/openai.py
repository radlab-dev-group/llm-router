"""
OpenAI‑compatible endpoint implementations.

The module provides a base response handler and concrete endpoint classes for
chat completions, generic completions, and model listing.  All endpoints inherit
common functionality from the ``PassthroughI`` abstract base class.
"""

import abc
import datetime

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.core.api_types.openai import OpenAIConverters
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.base.constants_base import OPENAI_COMPATIBLE_PROVIDERS
from llm_router_api.endpoints.passthrough import PassthroughI


class OpenAIResponseHandler(PassthroughI, abc.ABC):
    @staticmethod
    def prepare_response_function(response):
        """
        Convert a raw ``requests.Response`` into the OpenAI‑compatible JSON format.

        The helper checks whether the payload contains a ``"message"`` key – a
        pattern used by Ollama – and, if present, applies the appropriate
        conversion via :class:`OpenAIConverters.FromOllama`.  Otherwise the
        original JSON body is returned unchanged.

        Parameters
        ----------
        response : requests.Response
            The HTTP response object received from the downstream service.

        Returns
        -------
        dict
            A dictionary ready to be returned to the client in OpenAI‑compatible
            shape.
        """
        resp_json = response.json()
        if "message" in resp_json:
            return OpenAIConverters.FromOllama.convert(response=resp_json)
        if "content" in resp_json and "role" in resp_json and "id" in resp_json:
            # Anthropic response
            return OpenAIConverters.FromAnthropic.convert_response(resp_json)
        return resp_json


class OpenAIResponsesHandler(OpenAIResponseHandler):
    """
    Responses endpoint that re‑uses the chat implementation but targets the
    ``/responses`` route of an OpenAI‑compatible service.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="responses",
        direct_return=False,
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=True,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function


class OpenAIResponsesV1Handler(OpenAIResponseHandler):
    """
    Responses endpoint that re‑uses the chat implementation but targets the
    ``/responses`` route of an OpenAI‑compatible service.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="v1/responses",
        direct_return=False,
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=True,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function


class OpenAICompletionHandler(OpenAIResponseHandler):
    """
    Completion endpoint that re‑uses the chat implementation but targets the
    ``/chat/completions`` route of an OpenAI‑compatible service.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="chat/completions",
        direct_return=False,
    ):
        """
        Initialize the completion endpoint.

        Parameters are identical to :class:`OpenAIChat` except
        that the route defaults to ``"chat/completions"``.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function


class OpenAIEmbeddingsHandler(PassthroughI):
    """
    Embeddings endpoint that targets the ``/embeddings``
    route of an OpenAI‑compatible service.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="embeddings",
        direct_return=False,
    ):
        """
        Initialize the embeddings endpoint.

        Parameters are identical to :class:`OpenAIChat` except
        that the route defaults to ``"embeddings"``.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=True,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function

    @staticmethod
    def prepare_response_function(response):
        """
        Convert a raw ``requests.Response`` into the OpenAI‑compatible JSON format.

        The helper checks whether the payload contains a ``"message"`` key – a
        pattern used by Ollama – and, if present, applies the appropriate
        conversion via :class:`OpenAIConverters.FromOllama`.  Otherwise the
        original JSON body is returned unchanged.

        Parameters
        ----------
        response : requests.Response
            The HTTP response object received from the downstream service.

        Returns
        -------
        dict
            A dictionary ready to be returned to the client in OpenAI‑compatible
            shape.
        """
        response = response.json()
        if "embeddings" in response:
            return OpenAIConverters.FromOllama.convert_embedding(response=response)
        return response


class OpenAIEmbeddingsV1Handler(PassthroughI):
    """
    Embeddings endpoint that targets the ``/v1/embeddings``
    route of an OpenAI‑compatible service.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="v1/embeddings",
        direct_return=False,
    ):
        """
        Initialize the embeddings endpoint.

        Parameters are identical to :class:`OpenAIChat` except
        that the route defaults to ``"v1/embeddings"``.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=True,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=direct_return,
            method="POST",
        )


class OpenAICompletionHandlerWOApi(OpenAIResponseHandler):
    """
    Completion endpoint that re‑uses the chat implementation but targets the
    ``/chat/completions`` route of an OpenAI‑compatible service.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="chat/completions",
        direct_return=False,
    ):
        """
        Initialize the completion endpoint.

        Parameters are identical to :class:`OpenAIChat` except
        that the route defaults to ``"chat/completions"``.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=True,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function


class OpenAiV1ChatCompletion(OpenAIResponseHandler):
    """
    OpenAI‑compatible chat endpoin.

    The class inherits the full request‑validation, guard‑rail, and response‑
    handling logic from :class:`OpenAIResponseHandler`.  It only overrides the
    constructor to configure the endpoint name, supported API type, and the
    optional prompt/model handlers.

    Class attributes
    ----------------
    REQUIRED_ARGS : None
        vLLM does not enforce any mandatory request parameters beyond those
        already validated by the base class.
    OPTIONAL_ARGS : None
        No additional optional arguments are defined for this endpoint.
    SYSTEM_PROMPT_NAME : None
        System‑prompt injection is delegated to the base handler; this endpoint
        does not define a specific prompt name.
    """

    REQUIRED_ARGS = None
    OPTIONAL_ARGS = None
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[ModelHandler] = None,
        model_handler: Optional[PromptHandler] = None,
        ep_name="/v1/chat/completions",
        method="POST",
        dont_add_api_prefix: bool = True,
    ):
        """
        Initialize the OpenAI chat endpoint.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Log file name; defaults to the library’s standard configuration.
        logger_level : Optional[str]
            Logging level; defaults to :data:`REST_API_LOG_LEVEL`.
        prompt_handler : Optional[ModelHandler]
            Handler for prompt templates (passed through to the backend).
        model_handler : Optional[PromptHandler]
            Handler for model configuration.
        ep_name : str
            Endpoint name; defaults to ``"chat"``.
        method : str
            HTTP method to use; defaults to ``"POST"``.
        dont_add_api_prefix : bool
            If ``True`` the global API prefix is omitted.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=OPENAI_COMPATIBLE_PROVIDERS,
            method=method,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            direct_return=False,
        )

        self._prepare_response_function = self.prepare_response_function


class OpenAIModelsHandler(PassthroughI):
    """
    Endpoint that lists available models from an OpenAI‑compatible service.

    It overrides the HTTP method to ``GET`` and disables the global API
    prefix, exposing the route directly under ``/models``.
    """

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = True

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "models",
        dont_add_api_prefix=True,
        api_types: Optional[List[str]] = None,
        timestamp_as_int: bool = False,
    ):
        """
        Initialize the models‑listing endpoint.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Log file name; defaults to the library’s standard configuration.
        logger_level : Optional[str]
            Logging level; defaults to :data:`REST_API_LOG_LEVEL`.
        model_handler : Optional[ModelHandler]
            Handler providing access to model configuration.
        prompt_handler : Optional[PromptHandler]
            Prompt handler (unused for model listing).
        ep_name : str
            Endpoint name; defaults to ``"models"``.
        dont_add_api_prefix : bool
            When ``True`` the global API prefix is omitted.
        timestamp_as_int: bool, defaults as False
            If set to True, then timestamp will be converted as integer
        """
        super().__init__(
            ep_name=ep_name,
            method="GET",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            api_types=api_types or OPENAI_COMPATIBLE_PROVIDERS,
            direct_return=True,
        )

        self._timestamp_as_int = timestamp_as_int

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Return a static payload describing the model list.

        The endpoint does not accept any query parameters; ``params`` is ignored.

        Returns
        -------
        dict
            ``{"object": "list", "data": <list_of_models>}``.
        """
        # self.direct_return = True
        return {"object": "list", "data": self.__proper_models_list_format()}

    def __proper_models_list_format(self):
        """
        Transform the internal model registry into the OpenAI ``/models`` schema.

        The method gathers active model tags from the configured ``ModelHandler``,
        merges them into a flat list, and adds a creation timestamp (optionally
        as an integer) for each model entry.

        Returns
        -------
        list[dict]
            A list of model descriptors containing ``id``, ``object``, ``created``,
            and ``owned_by`` fields.
        """
        _models_data = self._api_type_dispatcher.tags(
            models_config=self._model_handler.list_active_models(),
            merge_to_list=True,
        )
        proper_models = []
        for m in _models_data:
            _t_stamp = datetime.datetime.now().timestamp()
            if self._timestamp_as_int:
                _t_stamp = int(_t_stamp)

            _model = {
                "id": m["id"],
                "object": m["object"],
                "created": _t_stamp,
                "owned_by": m["owned_by"],
            }
            proper_models.append(_model)
        return proper_models


class OpenAIModelsV1Handler(OpenAIModelsHandler):
    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "v1/models",
        dont_add_api_prefix=True,
        api_types: Optional[List[str]] = None,
    ):
        """
        Initialise the models‑listing endpoint.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Log file name; defaults to the library’s standard configuration.
        logger_level : Optional[str]
            Logging level; defaults to :data:`REST_API_LOG_LEVEL`.
        model_handler : Optional[ModelHandler]
            Handler providing access to model configuration.
        prompt_handler : Optional[PromptHandler]
            Prompt handler (unused for model listing).
        ep_name : str
            Endpoint name; defaults to ``"models"``.
        dont_add_api_prefix : bool
            When ``True`` the global API prefix is omitted.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            api_types=api_types or OPENAI_COMPATIBLE_PROVIDERS,
            timestamp_as_int=True,
        )
