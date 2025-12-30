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
from llm_router_api.core.api_types.openai import OpenAIConverters
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
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
        response = response.json()
        if "message" in response:
            return OpenAIConverters.FromOllama.convert(response=response)
        return response


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
            api_types=["openai", "lmstudio", "vllm"],
            direct_return=direct_return,
            method="POST",
        )

        # self._prepare_response_function = self.prepare_response_function


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
            api_types=["openai", "lmstudio", "vllm"],
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function


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
            api_types=["openai", "lmstudio"],
            direct_return=direct_return,
            method="POST",
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
            api_types=api_types or ["openai", "lmstudio"],
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
            api_types=api_types or ["openai", "lmstudio"],
            timestamp_as_int=True,
        )
