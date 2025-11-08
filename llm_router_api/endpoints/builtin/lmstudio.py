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

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.base.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.passthrough import PassthroughI


class LmStudioModelsHandler(PassthroughI):
    """
    Endpoint that returns the list of model identifiers available in the
    LM Studio service.

    The endpoint is registered under the name ``models`` and supports the
    HTTP ``GET`` method.  No request parameters are required; the response
    contains a ``models`` key with a list of model IDs.
    """

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
        dict
            A response containing the object type ``"list"`` and a ``data``
            field with the available model tags.
        """
        # models = self.__proper_models_list_format()
        models = self.__proper_models_list_format()
        # import json
        # print(json.dumps(models, indent=2, ensure_ascii=False))
        return {"models": models}

    def __proper_models_list_format(self):
        _models_data = self._api_type_dispatcher.tags(
            models_config=self._model_handler.list_active_models(),
            merge_to_list=True,
        )
        proper_models = []
        for m in _models_data:
            _model = {
                "type": "llm",
                "modelKey": m["id"],
                "format": "gguf",
                "displayName": m["id"],
                "path": m["id"],
                "sizeBytes": 4683073952,
                "paramsString": "7B",
                "architecture": "qwen2",
                "vision": False,
                "trainedForToolUse": True,
                "maxContextLength": 32768,
            }
            proper_models.append(_model)
        return proper_models
