"""
llm_proxy_rest.endpoints.builtin.openai
================================================

Endpoint implementations that proxy requests to OpenAI‑compatible back‑ends.
The module defines a base chat endpoint (:class:`OpenAIChat`) and two
derived classes for completions and model listing.
"""

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.passthrough import PassthroughI


class OpenAIChat(PassthroughI):
    """
    Base endpoint for forwarding chat‑style requests to an OpenAI‑compatible API.

    The class does not enforce any required or optional arguments; the
    concrete subclasses specify the appropriate HTTP method and route.
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
        ep_name="chat",
        method="POST",
        dont_add_api_prefix: bool = False,
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
            method=method,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
        )

    def endpoint_api_types(self) -> List[str]:
        """
        Declare the API families supported by this endpoint.

        Returns
        -------
        List[str]
            The endpoint works with both ``"openai"`` and ``"ollama"`` back‑ends.
        """
        return ["openai", "ollama"]


class OpenAICompletion(OpenAIChat):
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
        )


class OpenAIModels(OpenAIChat):
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
        )

    def endpoint_api_types(self) -> List[str]:
        """
        Declare the API families for the model‑listing endpoint.

        Returns
        -------
        List[str]
            Supports ``"openai"`` and ``"lmstudio"`` back‑ends.
        """
        return ["openai", "lmstudio"]

    @EP.response_time
    @EP.require_params
    def parametrize(
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
        return {
            "object": "list",
            "data": self._api_type_dispatcher.tags(
                models_config=self._model_handler.list_active_models(),
                merge_to_list=True,
            ),
        }
