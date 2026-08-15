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

from pydantic import BaseModel

from llm_router_lib.core.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_RETRIES,
)
from llm_router_lib.services.health import PingService, VersionService
from llm_router_lib.utils.http import HttpRequester
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_lib.services.utils import (
    TranslateTextService,
    GenerativeAnswerService,
    GenerateNewsFromTextService,
)
from llm_router_lib.services.conversation import (
    ConversationService,
    ExtendedConversationService,
)

# ------------------------------------------------------------------ #
# Type aliases for payload parameter union types (repeated across methods).
# ------------------------------------------------------------------ #
_ConvPayload = Union[Dict[str, Any], ConversationService.model_cls]
_ExtConvPayload = Union[Dict[str, Any], ExtendedConversationService.model_cls]


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
        timeout: int | None = None,
        retries: int | None = None,
        logger: logging.Logger | None = None,
        default_model: str | None = None,
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
        timeout : int, default ``DEFAULT_TIMEOUT_SECONDS``
            Seconds to wait for a response before timing out.
        retries : int, default ``DEFAULT_RETRIES``
            Number of automatic retry attempts for HTTP status codes defined in
            ``HttpRequester``'s retry policy.
        logger : logging.Logger | None
            Custom logger; if ``None`` a module‑level logger is created.
        default_model: str | None
            Default model name. Will be used in case when
            model_name in any service is not given
        """
        self.base_url = api.rstrip("/")
        self.token = token

        self.default_model = default_model

        # Resolve lazy defaults from the centralised constants module.
        effective_timeout = (
            timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS
        )
        effective_retries = retries if retries is not None else DEFAULT_RETRIES
        self.timeout = effective_timeout
        self.retries = effective_retries
        self.http = HttpRequester(
            base_url=self.base_url,
            token=self.token or "",
            timeout=effective_timeout,
            retries=effective_retries,
        )

        self.logger = logger or logging.getLogger(__name__)

    def close(self) -> None:
        """Close the underlying HTTP session to release resources."""
        self.http.close()

    def __enter__(self) -> "LLMRouterClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def ping(self) -> Dict[str, Any]:
        """
        Perform a health‑check request against the router.

        This method invokes the ``/api/ping`` endpoint via :class:`PingService`
        and returns the parsed JSON response.  It is useful for quickly
        confirming that the service is up and reachable before making more
        expensive calls.

        Returns
        -------
        dict
            The JSON payload returned by the router, typically containing a
            ``status`` field (e.g. ``{"status": "ok"}``).

        Raises
        ------
        LLMRouterError
            Propagated from the underlying service if the HTTP request fails
            or the response cannot be decoded as JSON.
        """
        return PingService(self.http, self.logger).call_get()

    def version(self) -> Dict[str, Any]:
        """
        Retrieve version information for the running router instance.

        Calls the ``/api/version`` endpoint via :class:`VersionService`.  The
        returned dictionary may include keys such as ``version``, ``commit_hash``,
        ``build_date`` or other metadata the backend provides.

        Returns
        -------
        dict
            Parsed JSON containing version‑related data.

        Raises
        ------
        LLMRouterError
            Propagated if the request fails or the response is not valid JSON.
        """
        return VersionService(self.http, self.logger).call_get()

    # ------------------------------------------------------------------ #
    def conversation_with_model(
        self,
        payload: _ConvPayload,
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

    def extended_conversation_with_model(
        self,
        payload: _ExtConvPayload,
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
        temperature: Optional[float] = 0.75,
        max_new_tokens: Optional[int] = 512,
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
        temperature: Optional[float]
            Temperature
        max_new_tokens: Optional[int]
            Max new tokens
        Returns
        -------
        dict
            Parsed JSON response from the translation service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is missing.
        """
        payload = self._build_payload(
            model_cls=TranslateTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return TranslateTextService(self.http, self.logger).call_post(payload)

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
        payload = self._build_payload(
            model_cls=GenerativeAnswerService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            question_str=question_str,
        )
        return GenerativeAnswerService(self.http, self.logger).call_post(payload)

    def generate_news_from_text(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerateNewsFromTextService.model_cls,
            ]
        ] = None,
        text: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self._build_payload(
            model_cls=GenerateNewsFromTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            text=text,
        )
        return GenerateNewsFromTextService(self.http, self.logger).call_post(payload)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_payload(
        *,
        model_cls: type | None,
        payload_arg: Any,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Normalize a payload to a ``dict``.

        Handles three input shapes and builds from keyword arguments when the
        caller passed individual parameters instead of a pre‑constructed payload:

        1. **Pydantic model instance** → serialised via ``model_dump()``.
        2. **Dict** → returned unchanged.
        3. **None** → constructed from *extra* keyword arguments using the
           provided *model_cls*; raises :class:`NoArgsAndNoPayloadError` if
           required keys are missing.
        """
        if isinstance(payload_arg, BaseModel):
            return payload_arg.model_dump()

        if isinstance(payload_arg, Dict):
            return payload_arg

        # Neither a model nor a dict — build from named parameters.
        if model_cls is not None and extra:
            return model_cls(**extra).model_dump()

        raise NoArgsAndNoPayloadError("No payload and no arguments were passed!")
