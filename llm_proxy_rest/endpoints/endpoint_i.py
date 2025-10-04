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
* ``parametrize`` – conversion of raw request parameters into the
  payload that will be sent to the downstream model or external API.

When ``SERVICE_AS_PROXY`` is ``True`` the endpoint also contains helper
methods for performing outbound HTTP requests to an external service.
"""

import abc
import json
import requests

from typing import Optional, Dict, Any, Iterator, Iterable, List

from rdl_ml_utils.utils.logger import prepare_logger
from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.base.model_handler import ModelHandler, ApiModel
from llm_proxy_rest.core.api_types.dispatcher import ApiTypesDispatcher, API_TYPES
from llm_proxy_rest.base.constants import (
    SERVICE_AS_PROXY,
    DEFAULT_EP_LANGUAGE,
    REST_API_LOG_LEVEL,
    REST_API_TIMEOUT,
    DEFAULT_API_PREFIX,
)
from llm_proxy_rest.core.data_models.constants import (
    MODEL_NAME_PARAMS,
    LANGUAGE_PARAM,
    SYSTEM_PROMPT,
)


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
        :class:`~llm_proxy_rest.base.model_handler.ApiModel` objects.
    _prompt_name: str | None
        Resolved system‑prompt identifier (populated by
        :meth:`_resolve_prompt_name`).
    _prompt_handler: PromptHandler | None
        Optional handler used to retrieve prompt templates.
    _dont_add_api_prefix: bool
        When ``True`` the endpoint URL is registered without the global
        API prefix (``/api/v1`` by default).
    _ep_types_str: List[str]
        List of API types.
    _api_type_dispatcher: ApiTypesDispatcher
        Helper used to map a model's API type to concrete endpoint URLs.
    _api_model: ApiModel | None
        Model configuration selected by :meth:`_set_model`.
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
        redirect_ep: bool = False,
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
            ``None`` the default ``llm-proxy-rest.log`` is used.
        model_handler :
            Optional :class:`~llm_proxy_rest.base.model_handler.ModelHandler`
            instance used to resolve model identifiers supplied by the
            client.
        prompt_handler :
            Optional :class:`~rdl_ml_utils.handlers.prompt_handler.PromptHandler`
            used to fetch or render system prompts.
        dont_add_api_prefix :
            If ``True`` the endpoint URL will be registered without the
            global ``DEFAULT_API_PREFIX`` prefix.
        redirect_ep:
            If ``True`` the endpoint URL will be registered to api host.

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

        self._prompt_name = None
        self._redirect_ep = redirect_ep
        self._prompt_handler = prompt_handler
        self._dont_add_api_prefix = dont_add_api_prefix

        self.logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name or "llm-proxy-rest.log",
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
        self.prepare_ep()

        self._api_model: Optional[ApiModel] = None

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
    def prompt_name(self):
        """
        Return the resolved system‑prompt identifier for the current request.

        The attribute is populated by :meth:`_resolve_prompt_name` during
        request processing.
        """
        return self._prompt_name

    @property
    def add_api_prefix(self):
        """
        Indicate whether the global API prefix (``DEFAULT_API_PREFIX``) should
        be prepended to the endpoint's URL when it is registered.

        ``True`` means *do not* add the prefix (i.e., the endpoint opts out).
        """
        return not self._dont_add_api_prefix

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
        # try:
        #     params = self.parametrize(params=params)
        #     self._set_model(params=params)
        #     self._resolve_prompt_name(params=params)
        # except Exception:
        #     raise
        raise NotImplementedError(
            "Method `run_ep` is not implemented for local models!"
        )

    @abc.abstractmethod
    def parametrize(
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

    def prepare_ep(self):
        """
        Hook called during construction to perform endpoint‑specific setup.

        The default implementation does nothing; concrete subclasses may
        override the method to preload resources, validate configuration
        files, or perform any other one‑time initialisation required
        before the first request is handled.
        """
        ...

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

    def _filter_allowed_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Strip out any keys that are not declared as required or optional.

        Unknown keys generate a warning via the instance logger but are
        otherwise ignored.

        Parameters
        ----------
        params :
            Raw request payload.

        Returns
        -------
        dict
            New dictionary containing only the parameters that appear in
            :attr:`REQUIRED_ARGS` or :attr:`OPTIONAL_ARGS`.
        """
        allowed = set(self.REQUIRED_ARGS or []) | set(self.OPTIONAL_ARGS or [])
        unknown = [k for k in params if k not in allowed]
        if unknown:
            self.logger.warning(
                f"Ignoring unknown argument(s) {unknown} for endpoint {self._ep_name}",
            )
            filtered_params = {k: v for k, v in params.items() if k in allowed}
        else:
            filtered_params = params
        return filtered_params

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
    def _set_model(self, params: Dict[str, Any]) -> None:
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

        Raises
        ------
        ValueError
            If the payload does not contain a recognised model key or the
            model name cannot be resolved via ``self._model_handler``.
        """
        # if self.REQUIRED_ARGS is None or not len(self.REQUIRED_ARGS):
        #     return

        model_name = None
        for m_name in MODEL_NAME_PARAMS:
            model_name = params.get(m_name)
            if model_name is not None:
                break

        if model_name is None:
            raise ValueError(
                f"Model name [{', '.join(MODEL_NAME_PARAMS)}] is required!"
            )

        api_model = self._model_handler.get_model(model_name=model_name)
        if api_model is None:
            raise ValueError(f"Model '{model_name}' not found in configuration")
        self._api_model = api_model

    def _resolve_prompt_name(self, params: Dict[str, Any]) -> None:
        """
        Determine which system‑prompt identifier should be used for the request.

        If :attr:`SYSTEM_PROMPT_NAME` is ``None`` the method falls back to the
        ``SYSTEM_PROMPT`` key supplied directly in *params*.  Otherwise the
        language code (``"en"``, ``"pl"``, …) is extracted and the corresponding
        entry from :attr:`SYSTEM_PROMPT_NAME` is stored in ``self._prompt_name``.

        Parameters
        ----------
        params :
            Request payload containing possible ``system_prompt`` and
            language information.
        """
        if self.SYSTEM_PROMPT_NAME is None:
            self._prompt_name = params.get(SYSTEM_PROMPT)
            return

        lang_str = self.__get_language(params=params)
        self._prompt_name = self.SYSTEM_PROMPT_NAME[lang_str]

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
        redirect_ep: bool = False,
        timeout: int = REST_API_TIMEOUT,
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
        redirect_ep:
            When ``True`` the endpoint is redirected to an external LLM
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
            redirect_ep=redirect_ep,
        )

        # End‑point specific URLs for chat and completions – populated later.
        # Chat
        self._d_chat_ep = None
        self._d_chat_method = None
        # Completions
        self._d_comp_ep = None
        self._d_comp_method = None

        self._timeout = timeout
        self.direct_return = False

    # ------------------------------------------------------------------
    # Core execution flow
    # ------------------------------------------------------------------
    def run_ep(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any] | Iterable[str | bytes]]:
        """
        Execute the endpoint logic for a request.

        The method first normalises the incoming parameters via
        :meth:`parametrize`.  When ``self.direct_return`` is set the
        normalised payload is returned verbatim.  Otherwise the method
        attempts to act as a *simple proxy*: if the endpoint's API type
        matches the model's API type, the request is forwarded to the
        downstream service (optionally as a streaming request).

        Parameters
        ----------
        params :
            Dictionary of request arguments extracted by the Flask registrar.

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
        self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))
        try:
            params = self.parametrize(params)
            if self.direct_return:
                return params

            # In case when the endpoint type is same as model endpoint type
            # Then llms is used as a simple proxy with forwarding params
            # and response from external api
            simple_proxy = False
            self._api_model = None

            # When the endpoint does not declare required arguments, we treat
            # it as a proxy that forwards the request to the model's own
            # endpoint.
            if not self.REQUIRED_ARGS:
                self._set_model(params=params)
                if self._api_model is None:
                    raise ValueError(f"API model not found in params {params}")

                self.logger.debug(self._api_model.as_dict())
                if self._api_model.api_type.lower() in self._ep_types_str:
                    simple_proxy = True

            if simple_proxy:
                ep_pref = ""
                if self.add_api_prefix and DEFAULT_API_PREFIX:
                    ep_pref = DEFAULT_API_PREFIX.strip()
                ep_url = ep_pref.strip("/") + "/" + self.name.lstrip("/")

                if bool((params or {}).get("stream", False)):
                    return self._call_http_request_stream(
                        ep_url=ep_url, params=params, leave_only_allowed=False
                    )
                response = self._call_http_request(
                    ep_url=ep_url, params=params, leave_only_allowed=False
                )

                self.logger.debug("=" * 100)
                self.logger.error(response)
                self.logger.debug("=" * 100)
                return response

            self._resolve_prompt_name(params=params)
            if self._prompt_name is not None:
                self.logger.debug(f" -> prompt_name: {self._prompt_name}")

            raise Exception("Only simple proxy or redirect is available!")
            # if self._api_model and self._prompt_name:
            #     self.__dispatch_external_api()
            #
            #     self.logger.debug(
            #         f" -> dispatched [{self._d_chat_method}] {self._d_chat_ep}"
            #     )
            #     self.logger.debug(
            #         f" -> dispatched [{self._d_comp_method}] {self._d_comp_ep}"
            #     )
            #
            #     return self._call_http_request(ep_url=self._d_chat_ep, params=params)

            return params
        except Exception as e:
            self.logger.exception(e)
            raise

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _call_http_request(
        self, ep_url: str, params: Dict[str, Any], leave_only_allowed: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Validate the payload and forward it to the remote service.

        The method optionally filters the supplied *params* to keep only those
        declared in :attr:`REQUIRED_ARGS` / :attr:`OPTIONAL_ARGS`,
        injects the model name, and then delegates to either
        :meth:`_call_post_with_payload` or :meth:`_call_get_with_payload`
        based on the endpoint's configured HTTP verb.

        Parameters
        ----------
        ep_url :
            Relative path (without host) that will be appended to the model's
            ``api_host``.
        params :
            Request payload.
        leave_only_allowed :
            When ``True`` (default) the payload is filtered to contain only
            allowed keys.

        Returns
        -------
        dict | None
            Parsed JSON response from the downstream service.
        """
        ep_url = self._api_model.api_host.rstrip("/") + "/" + ep_url.lstrip("/")

        if leave_only_allowed:
            params = self._filter_allowed_params(params=params)

        params["model"] = self._api_model.name

        if self._ep_method == "POST":
            return self._call_post_with_payload(ep_url=ep_url, params=params)
        return self._call_get_with_payload(ep_url=ep_url, params=params)

    def _call_http_request_stream(
        self, ep_url: str, params: Dict[str, Any], leave_only_allowed: bool = True
    ) -> Iterator[str | bytes]:
        """
        Stream the response from a remote endpoint without decoding.

        The implementation uses ``requests`` in streaming mode and yields raw
        NDJSON lines as UTF‑8 encoded ``bytes`` objects.

        Parameters
        ----------
        ep_url :
            Fully qualified URL to the external service.
        params :
            Request payload.
        leave_only_allowed :
            Whether to filter *params* before sending.

        Yields
        ------
        bytes
            Individual NDJSON lines terminated by a newline.
        """
        ep_url = self._api_model.api_host.rstrip("/") + "/" + ep_url.lstrip("/")

        if leave_only_allowed:
            params = self._filter_allowed_params(params=params)

        params["model"] = self._api_model.name
        params["stream"] = True

        method = (self._ep_method or "POST").upper()

        def _stream_iter() -> Iterator[str | bytes]:
            try:
                if method == "POST":
                    with requests.post(
                        ep_url, json=params, timeout=self._timeout, stream=True
                    ) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=False):
                            if line:  # Pomiń puste linie
                                yield (
                                    line.decode("utf-8", errors="replace") + "\n"
                                ).encode("utf-8")
                else:
                    with requests.get(
                        ep_url, params=params, timeout=self._timeout, stream=True
                    ) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=False):
                            if line:
                                yield (
                                    line.decode("utf-8", errors="replace") + "\n"
                                ).encode("utf-8")
            except requests.RequestException as exc:
                import json as _json

                err = {"error": str(exc)}
                yield (_json.dumps(err) + "\n").encode("utf-8")

        return _stream_iter()

    def _call_post_with_payload(
        self, ep_url: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Issue a JSON‑encoded ``POST`` request to the remote endpoint.

        Parameters
        ----------
        ep_url :
            Fully qualified URL.
        params :
            Payload to be JSON‑encoded.

        Returns
        -------
        dict | None
            Decoded JSON response or a ``{"raw_response": <text>}`` mapping
            when the response is not valid JSON.

        Raises
        ------
        RuntimeError
            If the request fails or the remote service returns a non‑2xx
            status code.
        """
        try:
            response = requests.post(ep_url, json=params, timeout=self._timeout)
        except requests.RequestException as exc:
            self.logger.exception(exc)
            raise RuntimeError(f"POST request to {ep_url} failed: {exc}") from exc
        return self.__return_http_response(response=response)

    def _call_get_with_payload(
        self, ep_url: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Issue a ``GET`` request with the supplied query parameters.

        Parameters
        ----------
        ep_url :
            Fully qualified URL.
        params :
            Mapping that will be turned into a query string.

        Returns
        -------
        dict | None
            Decoded JSON response or a ``{"raw_response": <text>}`` mapping
            when the response is not valid JSON.

        Raises
        ------
        RuntimeError
            If the request fails or the remote service returns a non‑2xx
            status code.
        """
        try:
            response = requests.get(ep_url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"GET request to {ep_url} failed: {exc}") from exc
        return self.__return_http_response(response=response)

    def __return_http_response(self, response):
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
            return response.json()
        except json.JSONDecodeError as e:
            self.logger.exception(e)
            return {"raw_response": response.text}

    #
    # def __dispatch_external_api(self) -> None:
    #     """
    #     Resolve concrete chat/completions endpoint URLs and HTTP methods.
    #
    #     The dispatcher examines the model's ``endpoint_api_types`` attribute
    #     and fills the internal ``_d_*`` attributes with the appropriate
    #     endpoint URLs and HTTP methods.  Any failure is logged and re‑raised.
    #
    #     Raises
    #     ------
    #     Exception
    #         Propagates any error raised by the dispatcher.
    #     """
    #     try:
    #         self._d_chat_ep = self._api_type_dispatcher.chat_ep(
    #             api_type=self._api_model.endpoint_api_types
    #         )
    #         self._d_chat_method = self._api_type_dispatcher.chat_method(
    #             api_type=self._api_model.endpoint_api_types
    #         )
    #         self._d_comp_ep = self._api_type_dispatcher.completions_ep(
    #             api_type=self._api_model.endpoint_api_types
    #         )
    #         self._d_comp_method = self._api_type_dispatcher.completions_method(
    #             api_type=self._api_model.endpoint_api_types
    #         )
    #     except (ValueError, Exception) as e:
    #         self.logger.exception(e)
    #         raise


BaseEndpointInterface = EndpointWithHttpRequestI if SERVICE_AS_PROXY else EndpointI
