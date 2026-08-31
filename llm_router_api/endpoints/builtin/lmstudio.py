"""
llm_router_api.endpoints.builtin.lmstudio
==========================================

Endpoint implementations for the **LM Studio** provider.  The module defines
separate endpoint classes for model listing, chat, and text generation, as
well as a concrete :class:`LmStudioType` that implements the
:class:`~llm_router_api.core.api_types.ApiTypesI` interface for LM Studio.

All endpoint classes inherit from :class:`EndpointWithHttpRequestI`,
a ``prepare_payload`` implementation, and the appropriate HTTP method configuration.
"""

from typing import cast, Any, Dict, Optional

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.builtin.openai import OpenAIResponseHandler
from llm_router_api.endpoints.passthrough import PassthroughI


class LmStudioModelsHandler(PassthroughI):
    """
    Endpoint that returns the list of model identifiers available in the
    LM Studio service.

    Registered at ``/api/v0/models`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``chat`` permission).
    """

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = True

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "v0/models",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            api_types=["lmstudio"],
            method="GET",
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
        Dict
            A response containing the object type ``"list"`` and a ``data``
            field with the available model tags.
        """
        return self.__proper_models_list_format()

    def __proper_models_list_format(self):
        _models_data = self._api_type_dispatcher.tags(
            models_config=(
                self._model_handler.list_active_models()
                if self._model_handler
                else {}
            ),
            merge_to_list=True,
        )
        proper_models = []
        for m in _models_data:
            m = cast(Dict[str, Any], m)
            _name = str(m.get("name") or m["id"])
            _publisher = m.get("publisher") or (
                _name.split("/", 1)[0] if "/" in _name else ""
            )
            proper_models.append(
                {
                    "id": m["id"],
                    "object": m["object"],
                    "type": "embeddings" if m.get("is_embedding") else "llm",
                    "publisher": _publisher,
                    "arch": m.get("arch") or "",
                    "compatibility_type": m.get("compatibility_type") or "",
                    "quantization": m.get("quantization") or "",
                    "state": "loaded",
                    "max_context_length": m["max_context_length"],
                }
            )

        _response = {"data": proper_models, "object": "list"}
        return _response


class LLMStudioChatV0Handler(OpenAIResponseHandler):
    """
    Completion endpoint that re‑uses the chat implementation but targets the
    ``/api/v0/chat/completions`` route of an OpenAI‑compatible service.

    Auth: **optional** — required only when ``LLM_ROUTER_AUTH_ENABLED=true``
    (``chat`` permission). Registered at ``/api/v0/chat/completions``.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="v0/chat/completions",
        direct_return=False,
    ):
        """
        Initialize the completion endpoint.

        Parameters are identical to :class:`OpenAIChat` except
        that the route defaults to ``/api/v0/chat/completions``.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            api_types=["lmstudio"],
            direct_return=direct_return,
            method="POST",
        )

        self._prepare_response_function = self.prepare_response_function
