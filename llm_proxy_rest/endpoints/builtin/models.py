from typing import Optional, Dict, Any

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import BaseEndpointInterface


class Tags(BaseEndpointInterface):
    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "tags",
        dont_add_api_prefix=False,
    ):
        super().__init__(
            ep_name=ep_name,
            method="GET",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
        )

    @EP.response_time
    @EP.require_params
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        self.direct_return = True
        return {
            "models": self._api_type_dispatcher.tags(
                models_config=self._model_handler.list_active_models(),
                merge_to_list=True,
            )
        }


#
#
# class OpenApiModels(Tags):
#     def __init__(
#         self,
#         logger_file_name: Optional[str] = None,
#         logger_level: Optional[str] = REST_API_LOG_LEVEL,
#         model_handler: Optional[ModelHandler] = None,
#         prompt_handler: Optional[PromptHandler] = None,
#         ep_name: str = "models",
#     ):
#         super().__init__(
#             ep_name=ep_name,
#             logger_level=logger_level,
#             logger_file_name=logger_file_name,
#             prompt_handler=prompt_handler,
#             model_handler=model_handler,
#             dont_add_api_prefix=True,
#         )
#
#
# class LmStudioModels(Tags):
#     def __init__(
#         self,
#         logger_file_name: Optional[str] = None,
#         logger_level: Optional[str] = REST_API_LOG_LEVEL,
#         model_handler: Optional[ModelHandler] = None,
#         prompt_handler: Optional[PromptHandler] = None,
#         ep_name: str = "v0/models",
#     ):
#         super().__init__(
#             ep_name=ep_name,
#             logger_level=logger_level,
#             logger_file_name=logger_file_name,
#             prompt_handler=prompt_handler,
#             model_handler=model_handler,
#             dont_add_api_prefix=False,
#         )
