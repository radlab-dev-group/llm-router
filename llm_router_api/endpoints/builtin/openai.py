"""
llm_router_api.endpoints.builtin.openai
================================================

Endpoint implementations that proxy requests to OpenAI‑compatible back‑ends.
The module defines a base chat endpoint (:class:`OpenAIChat`) and two
derived classes for completions and model listing.
"""

import datetime
from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.base.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.passthrough import PassthroughI


class OpenAICompletionHandler(PassthroughI):
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


class OpenAICompletionHandlerWOApi(PassthroughI):
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


class OpenAIModelsHandler(PassthroughI):
    """
    Endpoint that lists available models from an OpenAI‑compatible service.

    It overrides the HTTP method to ``GET`` and disables the global API
    prefix, exposing the route directly under ``/models``.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "models",
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
            method="GET",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            api_types=api_types or ["openai", "lmstudio"],
            direct_return=True,
        )

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Execute the model‑listing logic.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            Ignored – the endpoint does not accept query parameters.

        Returns
        -------
        dict
            A response containing the object type ``"list"`` and a ``data``
            field with the available model tags.
        """
        self.direct_return = True
        return {"object": "list", "data": self.__proper_models_list_format()}

    def __proper_models_list_format(self):
        _models_data = self._api_type_dispatcher.tags(
            models_config=self._model_handler.list_active_models(),
            merge_to_list=True,
        )
        proper_models = []
        for m in _models_data:
            _model = {
                "id": m["id"],
                "object": m["object"],
                "created": datetime.datetime.now().timestamp(),
                "owned_by": m["owned_by"],
            }
            proper_models.append(_model)
        return proper_models
