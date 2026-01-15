"""
High‑level client wrapper for the LLM‑Router API.

The :class:`LLMRouterClient` aggregates the low‑level ``HttpRequester`` with
the service‑layer classes (conversation, extended conversation, translation)
to provide a convenient, type‑safe Python interface.  Callers can pass either
a dictionary or a Pydantic model instance; the client takes care of converting
the model to a plain ``dict`` before invoking the appropriate service.
"""

import logging
from typing import Optional, Dict, Any, Union, List

from llm_router_lib.utils.http import HttpRequester
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_lib.services.ping import PingService
from llm_router_lib.services.models import AllModelsService
from llm_router_lib.services.utils import (
    TranslateTextService,
    GenerativeAnswerService,
)
from llm_router_lib.services.conversation import (
    ConversationService,
    ExtendedConversationService,
)


class LLMRouterClient:
    """
    Public client exposing the core LLM‑Router endpoints.

    The client hides the details of HTTP construction, retry handling and
    payload validation.  It is intended for use by downstream applications that
    need to interact with the router in a Pythonic way.

    Attributes
    ----------
    base_url : str
        Normalised base URL of the router API (trailing slash stripped).
    token : Optional[str]
        Bearer token used for authentication; may be ``None`` for unauthenticated
        endpoints.
    timeout : int
        Per‑request timeout in seconds.
    retries : int
        Number of retry attempts for transient HTTP errors.
    http : HttpRequester
        Helper instance that performs the actual HTTP calls.
    logger : logging.Logger
        Logger used for debugging and error reporting.
    """

    def __init__(
        self,
        api: str,
        token: Optional[str] = None,
        timeout: int = 10,
        retries: int = 2,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialise the client with connection settings.

        Parameters
        ----------
        api : str
            Base URL of the router (e.g. ``"https://router.example.com"``).
        token : Optional[str]
            Authentication token; if omitted the ``Authorization`` header is not
            sent.
        timeout : int, default ``10``
            Seconds to wait for a response before timing out.
        retries : int, default ``2``
            Number of automatic retry attempts for HTTP status codes defined in
            ``HttpRequester``’s retry policy.
        logger : Optional[logging.Logger]
            Custom logger; if ``None`` a module‑level logger is created.
        """
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
    def ping(self) -> Dict[str, Any]:
        return PingService(self.http, self.logger).call_get()

    # ------------------------------------------------------------------ #
    def models(self) -> Dict[str, Any]:
        return AllModelsService(self.http, self.logger).call_get()

    # ------------------------------------------------------------------ #
    def conversation_with_model(
        self,
        payload: Union[
            Dict[str, Any],
            ConversationService.model_cls,
        ],
    ) -> Dict[str, Any]:
        """
        Call the standard conversation endpoint.

        The method accepts either a raw dictionary or a
        :class:`GenerativeConversationModel` instance; in the latter case the
        model is serialised via ``model_dump()`` before the request is sent.

        Parameters
        ----------
        payload : Union[Dict[str, Any], GenerativeConversationModel]
            The request body to be forwarded to ``/api/conversation_with_model``.

        Returns
        -------
        dict
            Parsed JSON response from the router.
        """
        if isinstance(payload, ConversationService.model_cls):
            payload = payload.model_dump()

        return ConversationService(self.http, self.logger).call_post(payload)

    # ------------------------------------------------------------------ #
    def extended_conversation_with_model(
        self,
        payload: Union[
            Dict[str, Any],
            ExtendedConversationService.model_cls,
        ],
    ) -> Dict[str, Any]:
        """
        Call the extended conversation endpoint
        that supports an explicit system prompt.

        Parameters
        ----------
        payload : Union[Dict[str, Any], ExtendedGenerativeConversationModel]
            The request body for ``/api/extended_conversation_with_model``.

        Returns
        -------
        dict
            Parsed JSON response from the router.
        """
        if isinstance(payload, ExtendedConversationService.model_cls):
            payload = payload.model_dump()
        return ExtendedConversationService(self.http, self.logger).call_post(payload)

    # ------------------------------------------------------------------ #
    def translate(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                TranslateTextService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Translate a list of texts using the ``/api/translate`` endpoint.

        The method can be used in three ways:

        1. **Pass a ready‑made dictionary** – ``payload`` is a ``dict`` that already
           conforms to :class:`TranslateTextModel`.
        2. **Pass a Pydantic model instance** – ``payload`` is a
           ``TranslateTextModel`` and will be serialized automatically.
        3. **Provide ``texts`` and ``model`` arguments** – the client builds a
           ``TranslateTextModel`` instance on‑the‑fly.

        If neither a payload nor the ``texts``/``model`` pair is supplied, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Optional[Union[Dict[str, Any], TranslateTextModel]]
            Optional pre‑constructed request body.
        texts : Optional[List[str]]
            List of source strings to translate (required if ``payload`` is not
            supplied).
        model : Optional[str]
            Model identifier to be used for translation (required if ``payload``
            is not supplied).

        Returns
        -------
        dict
            Parsed JSON response from the translation service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is missing.
        """
        if isinstance(payload, TranslateTextService.model_cls):
            payload = payload.model_dump()
        elif isinstance(payload, Dict):
            payload = payload
        else:
            if not texts or not model:
                raise NoArgsAndNoPayloadError(
                    "No payload and no arguments were passed!"
                )
            payload = TranslateTextService.model_cls(
                model_name=model, texts=texts
            ).model_dump()

        return TranslateTextService(self.http, self.logger).call_post(payload)

    # ------------------------------------------------------------------ #
    def generative_answer(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerativeAnswerService.model_cls,
            ]
        ] = None,
        model: Optional[str] = None,
        texts: Optional[Dict[str, List[str]] | List[str]] = None,
        question_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        if isinstance(payload, GenerativeAnswerService.model_cls):
            payload = payload.model_dump()
        elif isinstance(payload, Dict):
            payload = payload
        else:
            if not texts or not question_str or not model:
                raise NoArgsAndNoPayloadError(
                    "No payload and no arguments were passed!"
                )
            payload = GenerativeAnswerService.model_cls(
                question_str=question_str, texts=texts, model_name=model
            ).model_dump()

        return GenerativeAnswerService(self.http, self.logger).call_post(payload)
