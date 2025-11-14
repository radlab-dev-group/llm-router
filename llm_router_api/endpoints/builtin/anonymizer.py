from typing import Optional, Dict, Any


from llm_router_lib.anonymizer.core import Anonymizer
from llm_router_lib.anonymizer.rules import ALL_ANONYMIZER_RULES

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.base.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL

from llm_router_lib.data_models.anonymizer import AnonymizerModel
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


class AnonymizeText(EndpointWithHttpRequestI):
    REQUIRED_ARGS = None
    OPTIONAL_ARGS = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "anonymize_text",
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=True,
        )

        self._anonymizer = Anonymizer(rules=ALL_ANONYMIZER_RULES)

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        options = AnonymizerModel(**params)
        return {"anonymized_text": self._do_text_anonymization(text=options.text)}

    def _do_text_anonymization(self, text: str) -> str:
        return self._anonymizer.anonymize(text=text)
