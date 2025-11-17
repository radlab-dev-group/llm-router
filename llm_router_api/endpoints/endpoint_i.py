"""
Endpoint abstraction layer for the LLM‑proxy REST service.

This module defines two abstract base classes that represent a
*single* HTTP endpoint.  Concrete implementations inherit from one of
these classes (selected by the ``SERVICE_AS_PROXY`` flag) and provide
the actual request handling logic.

The classes expose a small public API:

* ``name`` – the URL path of the endpoint.
* ``method`` – the HTTP verb (GET or POST) the endpoint expects.
* ``run_ep`` – the entry point called by the Flask registrar.
* ``prepare_payload`` – conversion of raw request parameters into the
  payload that will be sent to the downstream model or external API.

When ``SERVICE_AS_PROXY`` is ``True`` the endpoint also contains helper
methods for performing outbound HTTP requests to an external service.
"""

import abc
import json
import time

from typing import Optional, Dict, Any, Iterator, Iterable, List

from rdl_ml_utils.utils.logger import prepare_logger
from rdl_ml_utils.handlers.prompt_handler import PromptHandler


from llm_router_plugins.plugins.fast_masker.core.masker import FastMasker

from llm_router_lib.data_models.constants import (
    MODEL_NAME_PARAMS,
    LANGUAGE_PARAM,
)

from llm_router_api.base.model_handler import ModelHandler, ApiModel
from llm_router_api.base.constants import (
    DEFAULT_EP_LANGUAGE,
    REST_API_LOG_LEVEL,
    EXTERNAL_API_TIMEOUT,
    FORCE_ANONYMISATION,
)
from llm_router_api.endpoints.httprequest import HttpRequestExecutor

from llm_router_api.core.api_types.openai import OPENAI_ACCEPTABLE_PARAMS
from llm_router_api.core.api_types.dispatcher import ApiTypesDispatcher, API_TYPES


# ----------------------------------------------------------------------
# Public abstract base class – used when the service runs *not* as a proxy.
# ----------------------------------------------------------------------
class EndpointI(abc.ABC):
    """
    Abstract representation of a single REST endpoint.

    The class supplies a rich set of utilities for validation, logging,
    and standardized response formatting.

    Attributes
    ----------
    _ep_name: str
        Relative URL path of the endpoint (e.g. ``"chat/completions"``).
    _ep_method: str
        HTTP method this endpoint expects – ``"GET"`` or ``"POST"``.
    logger: logging.Logger
        Module‑level logger configured with the supplied log file and level.
    _model_handler: ModelHandler | None
        Optional handler used to resolve model names to concrete
        :class:`~llm_router_api.base.model_handler.ApiModel` objects.
    _prompt_handler: PromptHandler | None
        Optional handler used to retrieve prompt templates.
    _dont_add_api_prefix: bool
        When ``True`` the endpoint URL is registered without the global
        API prefix (``/api/v1`` by default).
    _ep_types_str: List[str]
        List of API types.
    _api_type_dispatcher: ApiTypesDispatcher
        Helper used to map a model's API type to concrete endpoint URLs.
    """

    METHODS = ["GET", "POST"]
    """Supported HTTP methods for any endpoint."""

    REQUIRED_ARGS = []
    """Names of parameters that **must** be supplied by the client."""

    OPTIONAL_ARGS = []
    """Names of parameters that are accepted but not required."""

    SYSTEM_PROMPT_NAME = {"pl": None, "en": None}
    """Mapping of language codes to system‑prompt identifiers."""

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        ep_name: str,
        api_types: List[str],
        method: str = "POST",
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        logger_file_name: Optional[str] = None,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        dont_add_api_prefix: bool = False,
        direct_return: bool = False,
        call_for_each_user_msg: bool = False,
    ):
        """
        Initialise an endpoint definition.

        Parameters
        ----------
        ep_name :
            URL fragment that identifies this endpoint (e.g. ``"chat"``).
        method :
            HTTP verb the endpoint will respond to; defaults to ``"POST"``.
            Must be one of :attr:`METHODS`.
        logger_level :
            Logging level name (``"INFO"``, ``"DEBUG"``, …).  If omitted the
            library default is used.
        logger_file_name :
            Path to a file where log records will be written.  When
            ``None`` the default ``llm-router.log`` is used.
        model_handler :
            Optional :class:`~llm_router_api.base.model_handler.ModelHandler`
            instance used to resolve model identifiers supplied by the
            client.
        prompt_handler :
            Optional :class:`~rdl_ml_utils.handlers.prompt_handler.PromptHandler`
            used to fetch or render system prompts.
        dont_add_api_prefix :
            If ``True`` the endpoint URL will be registered without the
            global ``DEFAULT_API_PREFIX`` prefix.
        direct_return:
            If ``True`` the payload is returned

        Raises
        ------
        RuntimeError
            If the endpoint does not declare any supported API types or
            if the declared types are not present in the global
            ``API_TYPES`` constant.
        ValueError
            If ``method`` is not listed in :attr:`METHODS`.
        """
        self._ep_name = ep_name
        self._ep_method = method
        self._model_handler = model_handler

        self.direct_return = direct_return
        self._prompt_handler = prompt_handler
        self._dont_add_api_prefix = dont_add_api_prefix

        self._call_for_each_user_msg = call_for_each_user_msg

        self.logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name or "llm-router.log",
            log_level=logger_level,
            use_default_config=True,
        )

        self._ep_types_str = api_types
        if self._ep_types_str is None or not len(self._ep_types_str):
            raise RuntimeError("Endpoint api type is required!")

        if not len(set(self._ep_types_str).intersection(set(API_TYPES))):
            raise RuntimeError(f"Supported api types are [{', '.join(API_TYPES)}]!")

        self._api_type_dispatcher = ApiTypesDispatcher()
        self._check_method_is_allowed(method=method)

        # Hook function to prepare response
        self._prepare_response_function = None

        # marker when ep stared
        self._start_time = None

        # Api anonymizer
        self._fast_masker: Optional[FastMasker] = None
        if FORCE_ANONYMISATION:
            self._prepare_anonymizer()

    # ------------------------------------------------------------------
    # Public read‑only properties
    # ------------------------------------------------------------------
    @property
    def name(self):
        """
        Return the raw endpoint name as supplied to the constructor.

        The value is used by the Flask registrar to build the final route.
        """
        return self._ep_name

    @property
    def method(self):
        """
        Return the HTTP verb this endpoint expects (``"GET"`` or ``"POST"``).
        """
        return self._ep_method

    @property
    def add_api_prefix(self):
        """
        Indicate whether the global API prefix (``DEFAULT_API_PREFIX``) should
        be prepended to the endpoint's URL when it is registered.

        ``True`` means *do not* add the prefix (i.e., the endpoint opts out).
        """
        return not self._dont_add_api_prefix

    @property
    def model_handler(self):
        return self._model_handler

    # ------------------------------------------------------------------
    # Core workflow
    # ------------------------------------------------------------------
    def run_ep(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any] | Iterable[str | bytes]]:
        """
        Execute the endpoint for a given request payload.

        Sub‑classes override this method to implement the complete request
        lifecycle (parameter validation, model resolution, prompt handling,
        external API dispatch, …).  The base implementation raises
        :class:`NotImplementedError` because the default behaviour
        depends on whether the service runs as a proxy or a local model.

        Parameters
        ----------
        params :
            Dictionary of request parameters extracted by the Flask
            registrar.  May be ``None`` for endpoints that do not expect
            any input.

        Returns
        -------
        dict | Iterable[bytes] | None
            The concrete result that will be JSON‑encoded (or streamed) back
            to the client.

        Raises
        ------
        NotImplementedError
            Always raised in the base class – concrete subclasses must
            provide an implementation.
        """
        raise NotImplementedError(
            "Method `run_ep` is not implemented for local models!"
        )

    @abc.abstractmethod
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Convert raw request parameters into the payload that will be sent to the
        downstream model or external service.

        Sub‑classes implement the business logic that interprets the incoming
        parameters, validates them (or delegates to :meth:`_check_required_params`),
        resolves the model to be used and returns a dictionary that represents
        the endpoint's response body.

        Parameters
        ----------
        params :
            Dictionary of parameters extracted from the HTTP request.
            May be ``None`` when the endpoint does not require input.

        Returns
        -------
        dict | None
            Normalised payload that will be forwarded to the downstream
            service, or ``None`` if the endpoint produces no output.

        Raises
        ------
        Exception
            Any exception raised will be caught by the Flask registrar and
            transformed into an appropriate HTTP error response.
        """
        raise NotImplementedError()

    # ------------------------------------------------------------------
    # Helper utilities for standardised JSON responses
    # ------------------------------------------------------------------
    @staticmethod
    def return_response_ok(body: Any) -> Dict[str, Any]:
        """
        Build a successful response payload.

        The wrapper follows the convention used throughout the project:
        ``{"status": True, "body": <user‑data>}``.

        Parameters
        ----------
        body :
            Arbitrary data that will be placed under the ``"body"`` key.

        Returns
        -------
        dict
            Mapping ready for JSON serialisation.
        """
        return {"status": True, "body": body}

    @staticmethod
    def return_response_not_ok(body: Optional[Any]) -> Dict[str, Any]:
        """
        Build an error response payload.

        If *body* is falsy (``None`` or empty) the resulting dictionary
        contains only the ``"status": False`` flag.  Otherwise the payload
        also includes a ``"body"`` key with the supplied value.

        Parameters
        ----------
        body :
            Optional error details or additional data to be returned to the
            client.

        Returns
        -------
        dict
            Mapping following the ``{"status": False, "body": ...}`` convention.
        """
        if body is None or not len(body):
            return {"status": False}
        return {"status": False, "body": body}

    @staticmethod
    def _get_choices_from_response(response):
        j_response = response.json()
        choices = j_response.get("choices", [])
        if not len(choices):
            if "message" in j_response:
                choices = [j_response]

        assistant_response = ""
        if len(choices):
            assistant_response = choices[0].get("message", {}).get("content")

        return j_response, choices, assistant_response

    def _prepare_anonymizer(self):
        """
        Actually as default FAST_MASKER is used.

        TODO: In the future:
        Check what type of anonymization should be used:
         - FAST_MASKER
         - PRIV_MASKER
         - GENAI_MASKER
        :return:
        """
        if self._fast_masker:
            return
        self._fast_masker = FastMasker()
        self.logger.debug("llm-router is running in force anonymization mode")

    # ------------------------------------------------------------------
    # Parameter validation helpers
    # ------------------------------------------------------------------
    def _check_required_params(self, params: Optional[Dict[str, Any]]) -> None:
        """
        Verify that all keys listed in :attr:`REQUIRED_ARGS` are present.

        Parameters
        ----------
        params :
            Dictionary of request parameters to validate.  ``None`` is treated
            as an empty mapping.

        Raises
        ------
        ValueError
            If any required key is missing from *params*.
        """
        if (
            params is None
            or self.REQUIRED_ARGS is None
            or not len(self.REQUIRED_ARGS)
        ):
            return

        missing = [arg for arg in self.REQUIRED_ARGS if arg not in params]
        if missing:
            raise ValueError(
                f"Missing required argument(s) {missing} "
                f"for endpoint {self._ep_name}"
            )

    def _check_method_is_allowed(self, method: str) -> None:
        """
        Ensure that *method* is one of the supported HTTP verbs.

        Parameters
        ----------
        method :
            HTTP method name to validate.

        Raises
        ------
        ValueError
            If *method* is not present in :attr:`METHODS`.
        """
        if method not in self.METHODS:
            _m_str = ", ".join(self.METHODS)
            raise ValueError(
                f"Unknown method {method}. Method must be one of {_m_str}"
            )

    # ------------------------------------------------------------------
    # Model‑related helpers (used by proxy endpoints)
    # ------------------------------------------------------------------
    def get_model_provider(
        self, params: Dict[str, Any], options: Optional[Dict[str, Any]] = None
    ) -> ApiModel:
        """
        Resolve the model identifier from *params* and store the matching
        :class:`ApiModel` instance.

        The method looks for any of the keys listed in
        :data:`MODEL_NAME_PARAMS` (e.g. ``"model"``, ``"engine"``, …).  If a
        matching model cannot be found, a :class:`ValueError` is raised.

        Parameters
        ----------
        params :
            Request payload from which the model name is extracted.

        options: Default: ``None``
            Options to use into the strategy

        Raises
        ------
        ValueError
            If the payload does not contain a recognised model key or the
            model name cannot be resolved via ``self._model_handler``.
        """
        # if self.REQUIRED_ARGS is None or not len(self.REQUIRED_ARGS):
        #     return
        model_name = self._model_name_from_params_or_model(params=params)
        api_model = self._model_handler.get_model_provider(
            model_name=model_name, options=options
        )
        if api_model is None:
            raise ValueError(f"Model '{model_name}' not found in configuration")
        return api_model

    def unset_model(
        self,
        api_model_provider: ApiModel,
        params: Dict[str, Any],
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not api_model_provider:
            return
        model_name = self._model_name_from_params_or_model(
            params=params, api_model_provider=api_model_provider
        )
        self._model_handler.put_model_provider(
            model_name=model_name,
            provider=api_model_provider.as_dict(),
            options=options,
        )

    @staticmethod
    def _model_name_from_params_or_model(
        params: Dict[str, Any], api_model_provider: Optional[ApiModel] = None
    ) -> str | None:
        model_name = None
        if api_model_provider:
            return api_model_provider.name

        for m_name in MODEL_NAME_PARAMS:
            model_name = params.get(m_name)
            if model_name is not None:
                break

        if model_name is None:
            raise ValueError(
                f"Model name [{', '.join(MODEL_NAME_PARAMS)}] is required!"
            )
        return model_name

    def _resolve_prompt_name(
        self,
        params: Dict[str, Any],
        map_prompt: Optional[Dict[str, str]],
        prompt_str_force: Optional[str] = None,
        prompt_str_postfix: Optional[str] = None,
    ) -> tuple[str | None, str | None]:
        prompt_str = None
        prompt_name: str | None = None
        if self.SYSTEM_PROMPT_NAME is not None:
            lang_str = self.__get_language(params=params)
            prompt_name = self.SYSTEM_PROMPT_NAME[lang_str]

        if prompt_str_force and len(prompt_str_force):
            prompt_str = prompt_str_force
        elif prompt_name:
            prompt_str = self._prompt_handler.get_prompt(prompt_name)

        if prompt_str and map_prompt:
            for _c, _t in map_prompt.items():
                prompt_str = prompt_str.replace(_c, _t)

        if prompt_str and prompt_str_postfix:
            prompt_str += "\n\n" + prompt_str_postfix

        if prompt_str:
            prompt_str = prompt_str.strip()
        return prompt_name, prompt_str

    @staticmethod
    def __get_language(params: Dict[str, Any]) -> str:
        """
        Extract the language code from a request payload.

        The function looks for the ``LANGUAGE_PARAM`` key and falls back to
        :data:`DEFAULT_EP_LANGUAGE` when the parameter is absent.

        Parameters
        ----------
        params :
            Request payload.

        Returns
        -------
        str
            Language identifier (e.g. ``"en"`` or ``"pl"``).
        """
        return params.get(LANGUAGE_PARAM, DEFAULT_EP_LANGUAGE)


# ----------------------------------------------------------------------
# Proxy‑enabled endpoint – performs outbound HTTP calls.
# ----------------------------------------------------------------------
class EndpointWithHttpRequestI(EndpointI, abc.ABC):
    """
    Abstract endpoint that forwards a request to an external LLM service.

    The class builds on :class:`EndpointI` by adding utilities for
    * validating required/optional parameters,
    * filtering out unknown keys,
    * constructing the final URL (optionally prefixed with the global API
      prefix), and
    * issuing the appropriate ``GET`` or ``POST`` request via the
      :mod:`requests` library.
    """

    class RetryResponse:
        """
        Configuration for automatic retry handling when an outbound HTTP
        request fails with a transient error.

        Attributes
        ----------
        RETRY_WHEN_STATUS : List[int]
            HTTP status codes that trigger a retry.  Includes client and
            server error codes that are typically recoverable (e.g. 429,
            503, 504, 500).
        TIME_TO_WAIT_SEC : float
            Number of seconds to wait between successive retry attempts.
        MAX_RECONNECTIONS : int
            Upper bound on how many retry attempts will be made before giving
            up.
        """

        # Code - definition
        #  * 400 - Raised by internal httprequest
        #  * 404 - Not Found
        #  * 503 - Service Unavailable
        #  * 504 - Gateway Timeout
        #  * > 500 - General error
        RETRY_WHEN_STATUS = [400, 404, 429, 503, 504, 500]
        TIME_TO_WAIT_SEC = 0.1
        MAX_RECONNECTIONS = 10

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        ep_name: str,
        api_types: List[str],
        method: str = "POST",
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        logger_file_name: Optional[str] = None,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        dont_add_api_prefix: bool = False,
        direct_return: bool = False,
        timeout: int = EXTERNAL_API_TIMEOUT,
        call_for_each_user_msg: bool = False,
    ):
        """
        Initialize the HTTP‑request‑enabled endpoint.

        All arguments are forwarded to :class:`EndpointI`.  In addition,
        the constructor creates a few attributes used for dispatching chat
        and completions endpoints and stores the request timeout.

        Parameters
        ----------
        ep_name :
            URL fragment that identifies the endpoint.
        method :
            HTTP verb; defaults to ``"POST"``.
        logger_level :
            Desired logging level; falls back to the library default.
        logger_file_name :
            Path to a file where log records will be written.
        prompt_handler :
            Optional handler for system prompts.
        model_handler :
            Optional handler for model configuration.
        dont_add_api_prefix :
            When ``True`` the global API prefix is omitted for this
            endpoint.
        direct_return:
            When ``True`` the payload is returned
        timeout :
            Number of seconds after which outbound HTTP calls will be
            aborted.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=api_types,
            method=method,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            model_handler=model_handler,
            prompt_handler=prompt_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            direct_return=direct_return,
            call_for_each_user_msg=call_for_each_user_msg,
        )

        self._timeout = timeout
        self._http_executor = HttpRequestExecutor(self)

    @property
    def timeout(self):
        """
        Return the request timeout (in seconds) configured for outbound
        HTTP calls made by this endpoint.

        The value is used by the internal :class:`HttpRequestExecutor` when
        performing ``GET``/``POST`` requests to external LLM services.
        """
        return self._timeout

    # ------------------------------------------------------------------
    # Core execution flow
    # ------------------------------------------------------------------
    def run_ep(
        self,
        params: Optional[Dict[str, Any]],
        reconnect_number: Optional[int] = 0,
        options: Optional[Dict] = None,
    ) -> Optional[Dict[str, Any] | Iterable[str | bytes]]:
        """
        Execute the endpoint logic for a request.

        The method first normalises the incoming parameters via
        :meth:`prepare_payload`.  When ``self.direct_return`` is set the
        normalised payload is returned verbatim.  Otherwise the method
        attempts to act as a *simple proxy*: if the endpoint's API type
        matches the model's API type, the request is forwarded to the
        downstream service (optionally as a streaming request).

        Parameters
        ----------
        params :
            Dictionary of request arguments extracted by the Flask registrar.

        reconnect_number: Defaults to ``0``.
            Number of times when the endpoint is trying to reconnect to the
            external host chosen by the provider.

        options: Defaults to ``None``.
            Additional options which may be passed f.e. to strategy

        Returns
        -------
        dict | Iterator[bytes] | None
            Either a normal JSON‑serialisable dictionary, a streaming NDJSON
            iterator, or ``None`` when the endpoint does not produce a
            response.

        Raises
        ------
        Exception
            Propagates any unexpected error; the Flask registrar will
            translate it into a 500 response.
        """
        orig_params = params.copy()
        api_model_provider = None
        clear_chosen_provider_finally = False

        # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

        self._start_time = time.time()
        try:
            params = self.prepare_payload(params)
            params = self._prepare_payload_at_beginning(payload=params)

            map_prompt = None
            prompt_str_force = None
            prompt_str_postfix = None
            if type(params) is dict:
                map_prompt = params.pop("map_prompt", {})
                prompt_str_force = params.pop("prompt_str_force", "")
                prompt_str_postfix = params.pop("prompt_str_postfix", "")

            # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

            # Testing: possible part to remove
            # if type(params) is dict:
            #     if not params.get("status", True):
            #         return params

            if self.direct_return:
                return params

            # In case when the endpoint type is same as model endpoint type
            # Then llms is used as a simple proxy with forwarding params
            # and response from external api
            simple_proxy = False

            # When the endpoint does not declare required arguments, we treat
            # it as a proxy that forwards the request to the model's own
            # endpoint.
            api_model_provider = self.get_model_provider(
                params=params, options=options
            )
            if api_model_provider is None:
                raise ValueError(f"API model not found in params {params}")
            clear_chosen_provider_finally = True

            _md = api_model_provider.as_dict().copy()
            if "api_token" in _md:
                _md["api_token"] = "***"
            self.logger.debug(f"Request model config: {_md}")

            if not self.REQUIRED_ARGS:
                if api_model_provider.api_type.lower() in self._ep_types_str:
                    simple_proxy = True

            prompt_name, prompt_str = self._resolve_prompt_name(
                params=params,
                map_prompt=map_prompt,
                prompt_str_force=prompt_str_force,
                prompt_str_postfix=prompt_str_postfix,
            )

            use_streaming = bool((params or {}).get("stream", False))

            # Prepare proper endpoint url
            ep_url = self._api_type_dispatcher.get_proper_endpoint(
                api_type=api_model_provider.api_type, endpoint_url=self.name
            )

            if simple_proxy and not use_streaming:
                return self._return_response_or_rerun(
                    api_model_provider=api_model_provider,
                    ep_url=ep_url,
                    prompt_str=prompt_str,
                    orig_params=orig_params,
                    params=params,
                    options=options,
                    reconnect_number=reconnect_number,
                )

            if prompt_name is not None:
                self.logger.debug(f" -> prompt_name: {prompt_name}")
                self.logger.debug(f" -> prompt_str: {str(prompt_str)[:40]}...")

            if api_model_provider.api_type in ["openai"]:
                params = self._filter_params_to_acceptable(
                    api_type=api_model_provider.api_type, params=params
                )

            if use_streaming:
                clear_chosen_provider_finally = False
                if self._call_for_each_user_msg:
                    raise ValueError(
                        "Streaming is available only for single message"
                    )

                is_generic_to_ollama = False
                is_ollama_to_generic = False
                is_ollama = (
                    "ollama" in self._ep_types_str
                    and "ollama" in api_model_provider.api_type
                )
                if not is_ollama:
                    if "ollama" in self._ep_types_str:
                        is_generic_to_ollama = True

                    if "ollama" in api_model_provider.api_type:
                        is_ollama_to_generic = True

                return self._http_executor.stream_response(
                    ep_url=ep_url,
                    params=params,
                    options=options,
                    is_ollama=is_ollama,
                    is_generic_to_ollama=is_generic_to_ollama,
                    is_ollama_to_generic=is_ollama_to_generic,
                    api_model_provider=api_model_provider,
                )

            return self._return_response_or_rerun(
                api_model_provider=api_model_provider,
                ep_url=ep_url,
                prompt_str=prompt_str,
                orig_params=orig_params,
                params=params,
                options=options,
                reconnect_number=reconnect_number,
            )
        except Exception as e:
            self.logger.exception(e)
            clear_chosen_provider_finally = True
            return self.return_response_not_ok(str(e))
        finally:
            if clear_chosen_provider_finally and api_model_provider is not None:
                self.unset_model(
                    api_model_provider=api_model_provider,
                    params=params,
                    options=options,
                )

    def _prepare_payload_at_beginning(
        self, payload: Dict[str, Any] | Any
    ) -> Dict[str, Any] | Any:
        """
        Perform early preprocessing of the incoming payload before the main
        business logic runs.

        The routine extracts a potential ``anonymize`` flag (or falls back to
        the global ``FORCE_ANONYMISATION`` setting), removes housekeeping
        fields such as ``response_time``, and optionally runs
        the method to clean payload.

        Parameters
        ----------
        payload : Union[Dict[Any, Any], Any]
            The raw request payload as received from the Flask layer.

        Returns
        -------
        Union[Dict[Any, Any], Any]
            The possibly anonymized payload ready for further processing.
        """
        # Remember general options before clear payload
        _anon_payload = FORCE_ANONYMISATION or payload.pop("anonymize", False)
        _anonymize_algorithm = payload.pop("anonymize_algorithm", None)
        _model_name_anonymize = payload.pop("model_name_anonymize", None)

        payload = self._clear_payload(payload=payload)
        if not _anon_payload:
            return payload
        return self._anonymize_payload(payload=payload)

    @staticmethod
    def _clear_payload(payload: Dict[str, Any]):
        """
        Remove internal‑only keys from the payload before it is sent to the
        downstream model.

        Currently the method strips the ``response_time`` key, which is used
        internally for logging and should not be forwarded.

        Parameters
        ----------
        payload : Dict[str, Any]
            The payload dictionary possibly containing internal keys.

        Returns
        -------
        Dict[str, Any]
            The payload with internal keys removed.
        """
        # Previously cleared arguments:
        #   * anonymize [_prepare_payload_at_beginning]
        #   * anonymize_algorithm [_prepare_payload_at_beginning]
        #   * model_name_anonymize [_prepare_payload_at_beginning]
        for k in ["response_time"]:
            payload.pop(k, "")

        # If stream param is not given, then set as False
        payload["stream"] = payload.get("stream", False)
        return payload

    def _anonymize_payload(self, payload: Dict | str | List | Any) -> Dict[str, Any]:
        """
        Apply the configured :class:`Anonymizer` to the supplied payload.

        The method lazily creates an :class:`Anonymizer` instance on first
        use and then forwards the payload to its ``anonymize_payload`` method.

        Parameters
        ----------
        payload : Union[Dict, str, List, Any]
            The data to be anonymized.

        Returns
        -------
        Dict[Any, Any]
            The anonymized representation of *payload*.
        """
        self._prepare_anonymizer()
        _p = self._fast_masker.mask_payload_fast(payload=payload)
        return _p

    def _return_response_or_rerun(
        self,
        api_model_provider,
        ep_url: str,
        prompt_str: str,
        orig_params: Dict,
        params: Dict,
        options: Dict,
        reconnect_number: int,
    ):
        """
        Send the prepared request to the external service and optionally retry
        on transient failures.

        The method delegates the actual HTTP call to
        :meth:`_http_executor.call_http_request`.  If the response status code
        matches one of the values defined in :class:`RetryResponse`, the call
        is retried up to ``MAX_RECONNECTIONS`` times with a short pause
        between attempts.

        Parameters
        ----------
        api_model_provider :
            The :class:`ApiModel` instance describing the target external
            service.
        ep_url : str
            Fully resolved endpoint URL to which the request will be sent.
        prompt_str : str
            Prompt text that may be injected into the request body.
        orig_params : dict
            The original request parameters (kept for possible retry).
        params : dict
            The processed parameters that will be sent to the external service.
        options : dict
            Additional options that may influence request handling.
        reconnect_number : int
            Current retry attempt counter.

        Returns
        -------
        dict | requests.Response | None
            The response from the external service, possibly after retries,
            or ``None`` if all attempts fail.
        """
        response = None
        status_code_force = None
        try:
            response = self._http_executor.call_http_request(
                ep_url=ep_url,
                params=params,
                prompt_str=prompt_str,
                api_model_provider=api_model_provider,
                call_for_each_user_msg=self._call_for_each_user_msg,
            )
        except Exception as e:
            self.logger.error(e)
            self.logger.error(response.text)
            status_code_force = 500

        self.unset_model(
            api_model_provider=api_model_provider, params=params, options=options
        )

        status_code = None or status_code_force
        if response and type(response) not in [dict]:
            status_code = response.status_code
        elif not response:
            status_code = 500
        #
        # print("====" * 20)
        # print(response)
        # print("status_code=", status_code)
        # print("====" * 20)

        if status_code and status_code in self.RetryResponse.RETRY_WHEN_STATUS:
            self.logger.warning(
                f" Provider {api_model_provider.id} responded with "
                f"{status_code}. Retrying {reconnect_number}/"
                f"{self.RetryResponse.MAX_RECONNECTIONS}."
            )

            if reconnect_number < self.RetryResponse.MAX_RECONNECTIONS:
                time.sleep(self.RetryResponse.TIME_TO_WAIT_SEC)
                if not options:
                    options = {}
                options["random_choice"] = True

                return self.run_ep(
                    params=orig_params,
                    reconnect_number=reconnect_number + 1,
                    options=options,
                )
            self.logger.error(f"Max reconnections exceeded: {reconnect_number}!")
        return response

    @staticmethod
    def _filter_params_to_acceptable(
        api_type: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        _params = {}
        if api_type == "openai":
            for p in OPENAI_ACCEPTABLE_PARAMS:
                if p in params:
                    _params[p] = params[p]
        else:
            raise Exception(f"Unsupported API type: {api_type}")
        return _params

    def return_http_response(self, response):
        """
        Normalize an HTTP response object into a Python dictionary.

        If the response status code indicates an error, a
        :class:`RuntimeError` is raised.  When the body cannot be parsed as
        JSON a ``{"raw_response": <text>}`` mapping is returned instead.

        Parameters
        ----------
        response:
            ``requests.Response`` object obtained from a ``GET`` or ``POST``
            call.

        Returns
        -------
        dict
            JSON payload or a raw‑response wrapper.

        Raises
        ------
        RuntimeError
            If ``response.ok`` is ``False``.
        """
        if not response.ok:
            raise RuntimeError(
                f"POST request to {self._ep_name} returned status "
                f"{response.status_code}: {response.text}"
            )
        try:
            if self._prepare_response_function:
                return self._prepare_response_function(response)
            return response.json()
        except json.JSONDecodeError as e:
            self.logger.exception(e)
            return {"raw_response": response.text}
