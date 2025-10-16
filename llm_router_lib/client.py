import logging
from typing import Optional, Dict, Any, Union

from llm_router_lib.data_models.builtin_chat import (
    GenerativeConversationModel,
    ExtendedGenerativeConversationModel,
)
from llm_router_lib.services.conversation import (
    ConversationService,
    ExtendedConversationService,
)
from llm_router_lib.utils.http import HttpRequester


class LLMRouterClient:

    def __init__(
        self,
        api: str,
        token: Optional[str] = None,
        timeout: int = 10,
        retries: int = 2,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = api.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.retries = retries
        self.http = HttpRequester(
            base_url=self.base_url,
            token=self.token,
            timeout=self.timeout,
            retries=self.retries,
        )
        self.logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------ #
    def conversation_with_model(
        self,
        payload: Union[
            Dict[str, Any],
            GenerativeConversationModel,
        ],
    ) -> Dict[str, Any]:
        if isinstance(payload, GenerativeConversationModel):
            payload = payload.model_dump()

        return ConversationService(self.http, self.logger).call(payload)

    # ------------------------------------------------------------------ #
    def extended_conversation_with_model(
        self,
        payload: Union[
            Dict[str, Any],
            ExtendedGenerativeConversationModel,
        ],
    ) -> Dict[str, Any]:
        if isinstance(payload, ExtendedGenerativeConversationModel):
            payload = payload.model_dump()
        return ExtendedConversationService(self.http, self.logger).call(payload)
