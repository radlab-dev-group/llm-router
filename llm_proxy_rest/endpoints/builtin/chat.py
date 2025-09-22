from typing import Optional, Dict, Any

from pydantic import ValidationError

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.endpoints.endpoint_i import EndpointI
from llm_proxy_rest.endpoints.data_models.genai import (
    GenerativeConversationModel,
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
)


class GenerativeOptionsEndpoint(EndpointI):
    REQUIRED_ARGS = GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = GENAI_CONV_OPT_ARGS

    def __init__(self, logger_file_name: Optional[str] = None):
        super().__init__(
            ep_name="conversation_with_model",
            method="POST",
            logger_file_name=logger_file_name,
        )

    @EP.require_params
    def call(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            options = GenerativeConversationModel(**params)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

        return self.return_response_ok(options.model_dump())
