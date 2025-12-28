"""
Conversation‑style endpoints built on top of the generic HTTP‑request base.

The module defines two concrete endpoint classes that translate incoming
client payloads into the format expected by the downstream model service and
post‑process the model’s response into a friendly JSON structure.
"""

import time
from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_lib.data_models.builtin_chat import (
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
    GenerativeConversationModel,
    ExtendedGenerativeConversationModel,
)
from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


class ConversationWithModel(EndpointWithHttpRequestI):
    REQUIRED_ARGS = GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = GENAI_CONV_OPT_ARGS
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/chat-conversation-simple",
        "en": "builtin/system/en/chat-conversation-simple",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "conversation_with_model",
    ):
        """
        Initialize a chat‑conversation endpoint for the built‑in model.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Path to a log file; falls back to the library default when ``None``.
        logger_level : Optional[str]
            Logging verbosity (e.g. ``"INFO"``, ``"DEBUG"``).  Defaults to
            :data:`REST_API_LOG_LEVEL`.
        prompt_handler : Optional[PromptHandler]
            Handler used to fetch system‑prompt templates.
        model_handler : Optional[ModelHandler]
            Handler that resolves model identifiers.
        ep_name : str
            URL fragment used when registering the Flask route.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Convert the incoming request into the payload expected by the model.

        The method validates required fields via the pydantic model
        :class:`GenerativeConversationModel`, renames ``model_name`` to ``model``,
        and builds the ``messages`` list required by the downstream service.
        Historical conversation turns are prepended when present.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            Raw request parameters supplied by the client.

        Returns
        -------
        dict
            Normalised payload ready for HTTP forwarding.
        """
        options = GenerativeConversationModel(**params)
        _payload = options.model_dump()
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": _payload["user_last_statement"],
            },
        ]

        _history = self.__prepare_history(payload=_payload)
        if len(_history):
            _payload["messages"] = _history + _payload["messages"]

        if "historical_messages" in _payload:
            _payload.pop("historical_messages")

        return _payload

    @staticmethod
    def __prepare_history(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Transform the ``historical_messages`` field into a list of role‑content dicts.

        Parameters
        ----------
        payload : Dict[str, Any]
            The intermediate payload that may contain a ``historical_messages`` key.

        Returns
        -------
        List[Dict[str, Any]]
            Ordered list of messages (``role`` + ``content``) to prepend to the
            current request.
        """
        history = []
        for m in payload["historical_messages"]:
            if "user" in m:
                history.append({"role": "user", "content": m["user"]})
            if "assistant" in m:
                history.append({"role": "assistant", "content": m["assistant"]})
        return history

    def __prepare_response_function(self, response):
        """
        Extract the assistant’s answer and compute the request duration.

        The helper uses the shared ``_get_choices_from_response`` method to
        obtain the final assistant message and then returns a dictionary with
        the generated text and the elapsed time.

        Parameters
        ----------
        response : requests.Response
            The HTTP response object received from the downstream model service.

        Returns
        -------
        dict
            ``{"response": <assistant_text>, "generation_time": <seconds>}``.
        """
        j_response, choices, assistant_response = self._get_choices_from_response(
            response=response
        )

        return {
            "response": assistant_response,
            "generation_time": time.time() - self._start_time,
        }


class ExtendedConversationWithModel(ConversationWithModel):
    REQUIRED_ARGS = EXT_GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = EXT_GENAI_CONV_OPT_ARGS
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "extended_conversation_with_model",
    ):
        """
        Initialize the extended conversation endpoint that supports system prompts.

        Parameters are identical to :class:`ConversationWithModel` except that
        ``model_handler`` and ``prompt_handler`` may be swapped.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Build a payload that includes an explicit system prompt.

        The method validates the request using the pydantic model
        :class:`ExtendedGenerativeConversationModel`, inserts the system prompt,
        and appends the user’s last statement together with any historical
        messages supplied by the client.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            Raw request data from the client.

        Returns
        -------
        dict
            Normalised payload ready for the downstream model.
        """
        options = ExtendedGenerativeConversationModel(**params)
        _payload = options.model_dump()
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "system",
                "content": _payload["system_prompt"],
            },
            {
                "role": "user",
                "content": _payload["user_last_statement"],
            },
        ] + _payload["historical_messages"]
        return _payload
