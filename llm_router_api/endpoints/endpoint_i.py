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
import time
import json
import logging
import datetime

from copy import deepcopy
from typing import Optional, Dict, Any, Iterator, Iterable, List

from rdl_ml_utils.utils.logger import prepare_logger
from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_plugins.utils.pipeline import UtilsPipeline
from llm_router_plugins.maskers.pipeline import MaskerPipeline
from llm_router_plugins.guardrails.pipeline import GuardrailPipeline

from llm_router_lib.data_models.constants import (
    MODEL_NAME_PARAMS,
    LANGUAGE_PARAM,
    CLEAR_PREDEFINED_PARAMS,
)

from llm_router_api.base.constants import (
    USE_PROMETHEUS,
    DEFAULT_EP_LANGUAGE,
    REST_API_LOG_LEVEL,
    EXTERNAL_API_TIMEOUT,
    FORCE_MASKING,
    MASKING_WITH_AUDIT,
    MASKING_STRATEGY_PIPELINE,
    FORCE_GUARDRAIL_REQUEST,
    GUARDRAIL_WITH_AUDIT_REQUEST,
    GUARDRAIL_STRATEGY_PIPELINE_REQUEST,
    FORCE_GUARDRAIL_RESPONSE,
    GUARDRAIL_STRATEGY_PIPELINE_RESPONSE,
    GUARDRAIL_WITH_AUDIT_RESPONSE,
    UTILS_PLUGINS_PIPELINE,
)

from llm_router_api.core.auditor.auditor import AnyRequestAuditor
from llm_router_api.core.model_handler import ModelHandler, ApiModel
from llm_router_api.core.api_types.openai import OPENAI_ACCEPTABLE_PARAMS
from llm_router_api.core.api_types.dispatcher import ApiTypesDispatcher, API_TYPES

from llm_router_api.endpoints.httprequest import HttpRequestExecutor


if USE_PROMETHEUS:
    from llm_router_api.core.metrics_handler import MetricsHandler


class SecureEndpointI(abc.ABC):
    EP_DONT_NEED_GUARDRAIL_AND_MASKING = False

    def __init__(self, ep_name: str, method: str, logger: logging.Logger):

        self.logger = logger
        self._ep_name = ep_name
        self._ep_method = method
        self._metrics = MetricsHandler() if USE_PROMETHEUS else None

        # --------------------------------------------------------------------------
        # ----------- MASKER SECTION
        # Masker pipeline definition
        self._masker_pipeline = None
        if FORCE_MASKING:
            self._prepare_masker_pipeline(plugins=MASKING_STRATEGY_PIPELINE)
        self._mask_auditor = None
        if MASKING_WITH_AUDIT:
            self._mask_auditor = AnyRequestAuditor(logger=self.logger)

        # --------------------------------------------------------------------------
        # ----------- GUARDRAILS SECTION
        # Guardrails (request) pipeline definition
        self._guardrails_pipeline_request = None
        if FORCE_GUARDRAIL_REQUEST:
            self._prepare_guardrails_pipeline(
                plugins=GUARDRAIL_STRATEGY_PIPELINE_REQUEST, for_response_mode=False
            )
        self._guardrail_auditor_request = None
        if GUARDRAIL_WITH_AUDIT_REQUEST:
            self._guardrail_auditor_request = AnyRequestAuditor(logger=self.logger)
        # --------------------------------------------------------------------------
        # Guardrails (response) pipeline definition
        self._guardrails_pipeline_response = None
        if FORCE_GUARDRAIL_RESPONSE:
            self._prepare_guardrails_pipeline(
                plugins=GUARDRAIL_STRATEGY_PIPELINE_RESPONSE,
                for_response_mode=True,
            )
        self._guardrail_auditor_response = None
        if GUARDRAIL_WITH_AUDIT_RESPONSE:
            self._guardrail_auditor_response = AnyRequestAuditor(logger=self.logger)

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

    # ------------------------------------------------------------------
    def _prepare_masker_pipeline(self, plugins: List[str]):
        if self._masker_pipeline:
            return

        self._masker_pipeline = MaskerPipeline(
            plugin_names=plugins, logger=self.logger
        )
        self.logger.debug(
            f"llm-router pipeline which will be used to masking: {plugins}"
        )

    def _prepare_guardrails_pipeline(
        self, plugins: List[str], for_response_mode: bool
    ):
        if for_response_mode and self._guardrails_pipeline_response:
            return
        elif not for_response_mode and self._guardrails_pipeline_request:
            return

        resp_str = "request"
        if for_response_mode:
            resp_str = "response"
            self._guardrails_pipeline_response = GuardrailPipeline(
                plugin_names=plugins, logger=self.logger
            )
        else:
            self._guardrails_pipeline_request = GuardrailPipeline(
                plugin_names=plugins, logger=self.logger
            )

        self.logger.debug(
            f"llm-router pipeline which will be used "
            f"to {resp_str} guardrails: {plugins}"
        )

    def _begin_audit_log_if_needed(
        self, payload, prepare_audit_log: bool, audit_type: str
    ):
        audit_log = None
        if prepare_audit_log:
            audit_log = {
                "endpoint": self.name,
                "audit_type": audit_type,
                "begin": {
                    "timestamp": datetime.datetime.now().timestamp(),
                    "payload": deepcopy(payload),
                },
            }
        return audit_log

    @staticmethod
    def _end_audit_log_if_needed(
        payload, audit_log, auditor: AnyRequestAuditor, force_end: bool
    ):
        if not audit_log:
            if force_end:
                raise Exception(f"Cannot end audit! Audit log is not set!")
            return

        if force_end or audit_log["begin"]["payload"] != payload:
            audit_log["end"] = {
                "timestamp": datetime.datetime.now().timestamp(),
                "payload": deepcopy(payload),
            }
            auditor.add_log(audit_log)

    def _is_request_guardrail_safe(self, payload: Dict):
        if (
            self.EP_DONT_NEED_GUARDRAIL_AND_MASKING
            or not self._guardrails_pipeline_request
        ):
            return True

        audit_log = self._begin_audit_log_if_needed(
            payload=payload,
            prepare_audit_log=GUARDRAIL_WITH_AUDIT_REQUEST,
            audit_type="guardrail_request",
        )

        is_safe, message = self._guardrails_pipeline_request.apply(payload=payload)

        if not is_safe and audit_log:
            self._end_audit_log_if_needed(
                payload=message,
                audit_log=audit_log,
                auditor=self._guardrail_auditor_request,
                force_end=True,
            )

        if not is_safe and self._metrics:
            self._metrics.inc_guardrail_incident()

        return is_safe

    def _guardrail_response_if_needed(self, response):
        return response

    def _do_masking_if_needed(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if (
            self.EP_DONT_NEED_GUARDRAIL_AND_MASKING
            or not payload
            or type(payload) is not dict
        ):
            return payload

        do_masking = FORCE_MASKING or bool(payload.get("anonymize", False))
        if not do_masking:
            return payload

        audit_log = self._begin_audit_log_if_needed(
            payload=payload,
            prepare_audit_log=MASKING_WITH_AUDIT,
            audit_type="masking",
        )
        masked_payload = self._mask_whole_payload(
            payload=payload,
            algorithms=MASKING_STRATEGY_PIPELINE,
        )

        if masked_payload != payload and self._metrics:
            self._metrics.inc_masker_incident()

        payload = masked_payload

        self._end_audit_log_if_needed(
            payload=payload,
            audit_log=audit_log,
            auditor=self._mask_auditor,
            force_end=False,
        )

        return payload

    def _mask_whole_payload(
        self,
        payload: Dict | str | List | Any,
        algorithms: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Apply the :class:`MaskerPipeline` to the supplied payload.

        The method lazily creates a MaskerPipeline

        Parameters
        ----------
        payload : Union[Dict, str, List, Any]
            The data to be masked.

        Returns
        -------
        Dict[Any, Any]
            The masked representation of *payload*.
        """
        self._prepare_masker_pipeline(plugins=algorithms)
        _p = self._masker_pipeline.apply(payload=payload)
        return _p


# ----------------------------------------------------------------------
# Public abstract base class – used when the service runs *not* as a proxy.
# ----------------------------------------------------------------------
class EndpointI(SecureEndpointI, abc.ABC):
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
        :class:`~llm_router_api.core.model_handler.ApiModel` objects.
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
            Optional :class:`~llm_router_api.core.model_handler.ModelHandler`
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
        super().__init__(
            ep_name=ep_name,
            method=method,
            logger=prepare_logger(
                logger_name=__name__,
                logger_file_name=logger_file_name or "llm-router.log",
                log_level=logger_level,
                use_default_config=True,
            ),
        )

        # --------------------------------------------------------------------------
        # Add utils pipeline if needed
        self._utils_pipeline = None
        if UTILS_PLUGINS_PIPELINE:
            self._prepare_utils_pipeline(plugins=UTILS_PLUGINS_PIPELINE)

        # --------------------------------------------------------------------------
        self._model_handler = model_handler

        self.direct_return = direct_return
        self._prompt_handler = prompt_handler
        self._dont_add_api_prefix = dont_add_api_prefix

        self._call_for_each_user_msg = call_for_each_user_msg

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

    # ------------------------------------------------------------------
    # Public read‑only properties
    # ------------------------------------------------------------------
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

    def return_response_not_ok(self, body: Optional[Any]) -> Any:
        """
        Build an error response payload with an appropriate HTTP status code.

        Parameters
        ----------
        body : Optional[Any]
            The error information that may be an exception instance, a string,
            a dictionary, or ``None``. The function attempts to extract an HTTP
            status code from known exception attributes and falls back to heuristics.

        Returns
        -------
        Tuple[dict, int]
            A tuple where the first element is a JSON‑serialisable dictionary
            representing the error payload and the second element is the HTTP
            status code. Flask interprets this as ``(Response, Status)``.
        """
        # Attempt to extract a status code from an exception object (if body is one)
        status_code = 500
        if hasattr(body, "response") and hasattr(body.response, "status_code"):
            # e.g., for ``requests.exceptions.HTTPError``
            status_code = body.response.status_code
        elif hasattr(body, "status_code") and isinstance(body.status_code, int):
            # e.g., for OpenAI ``APIError`` exceptions
            status_code = body.status_code
        elif str(body).lower().find("not found") != -1:
            # Heuristic for plain text (if body is a string)
            status_code = 404

        error_message = str(body) if body else "Error while processing"
        if any(t in self._ep_types_str for t in ["ollama", "openai", "vllm"]):
            error_body = {
                "error": {
                    "message": error_message,
                    "type": "api_error",  # or ``invalid_request_error``
                    "param": None,
                    "code": status_code,
                }
            }
        else:
            if body is None or not str(body):
                error_body = {"status": False}
            else:
                error_body = {"status": False, "body": str(body)}

        return error_body, status_code

    # ------------------------------------------------------------------
    # Model‑related helpers (used by proxy endpoints)
    # ------------------------------------------------------------------
    def get_model_provider(
        self,
        params: Dict[str, Any],
        options: Optional[Dict[str, Any]] = None,
        fake: bool = False,
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

        fake: Default: ``False``
            If ``True``, a fake model will be returned, LB strategy does not matter

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
            model_name=model_name, options=options, fake=fake
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

    # ------------------------------------------------------------------
    # Pipelines creation and handling
    # ------------------------------------------------------------------
    def _prepare_utils_pipeline(self, plugins: List[str]):
        """
        Prepare the utils pipeline if it has not been initialized.

        The method verifies whether the internal utils pipeline has already
        been created. If it exists, the function returns immediately. Otherwise,
        it creates a new ``UtilsPipeline`` using the supplied plugin names and
        the instance logger and logs the configured plugins at debug level.

        :param plugins: List of plugin identifiers to be loaded into the utils
            pipeline.
        :return: ``None`` – the method modifies the instance state as a side effect.
        """
        if self._utils_pipeline:
            return

        try:
            self._utils_pipeline = UtilsPipeline(
                plugin_names=plugins, logger=self.logger
            )
        except Exception as e:
            raise e

        self.logger.debug(f"llm-router utils pipeline: {plugins}")

    def _run_utils_plugins(self, payload: Dict):
        """
        Run the optional *utils* pipeline on the request payload.

        The ``UTILS_PLUGINS_PIPELINE`` setting can wire a series of
        plug‑ins that perform generic preprocessing (e.g. enrichment,
        validation, transformation).  If such a pipeline has been created
        by ``_prepare_utils_pipeline`` this method forwards the payload to
        it; otherwise the payload is returned untouched.

        Parameters
        ----------
        payload : Dict
            The normalized request payload produced by ``prepare_payload``
            and possibly altered by guard‑rail or masking steps.

        Returns
        -------
        Dict
            The payload after all utils plugins have been applied, or the
            original payload when no utils pipeline is configured.
        """
        if not self._utils_pipeline:
            return payload
        return self._utils_pipeline.apply(payload)

    # ------------------------------------------------------------------
    # Parameter validation and helper methods
    # ------------------------------------------------------------------
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
        use_streaming = bool((params or {}).get("stream", False))

        # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

        self._start_time = time.time()
        try:
            # ------------ BEGIN SECTION
            # 0.0 There user is able to prepare a payload to process
            params = self.prepare_payload(params)
            # 0.1 Run utils plugins which may modify the user context
            params = self._run_utils_plugins(payload=params)

            # ------------ BEGIN SECURE SECTION ------------
            # 1. Check payload using guardrails
            if not self._is_request_guardrail_safe(payload=params):
                if use_streaming:
                    api_model_provider = self.get_model_provider(
                        params=params, options=options, fake=True
                    )

                    is_generic_to_ollama, is_ollama_to_generic, is_ollama = (
                        self._resolve_stream_type(api_model_provider)
                    )

                    return self._http_executor.stream_response(
                        ep_url="",
                        params=params,
                        options=options,
                        is_ollama=is_ollama,
                        is_generic_to_ollama=is_generic_to_ollama,
                        is_ollama_to_generic=is_ollama_to_generic,
                        api_model_provider=api_model_provider,
                        force_text="Content blocked by guardrail. Reason: Not safe content!",
                    )

                return self.return_response_not_ok(
                    body={"reason": "guardrail", "error": "Not safe content!"}
                )

            # 2. Mask the whole payload if needed
            params = self._do_masking_if_needed(payload=params)

            # 3. Clear payload to accept only required params
            params = self._clear_payload(payload=params)
            # ------------ END SECURE SECTION ------------

            # 4. Endpoint processing
            map_prompt = None
            prompt_str_force = None
            prompt_str_postfix = None
            if type(params) is dict:
                map_prompt = params.pop("map_prompt", {})
                prompt_str_force = params.pop("prompt_str_force", "")
                prompt_str_postfix = params.pop("prompt_str_postfix", "")

            # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

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

            # Modify params specified for the chosen provider
            params = self._prepare_params_for_provider(
                params=params, model_provider=api_model_provider
            )

            clear_chosen_provider_finally = True

            self.logger.debug(f"Request model config id: {api_model_provider.id}")

            if not self.REQUIRED_ARGS:
                if api_model_provider.api_type.lower() in self._ep_types_str:
                    simple_proxy = True

            prompt_name, prompt_str = self._resolve_prompt_name(
                params=params,
                map_prompt=map_prompt,
                prompt_str_force=prompt_str_force,
                prompt_str_postfix=prompt_str_postfix,
            )

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

                is_generic_to_ollama, is_ollama_to_generic, is_ollama = (
                    self._resolve_stream_type(api_model_provider)
                )

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
            return self.return_response_not_ok(e)
        finally:
            if clear_chosen_provider_finally and api_model_provider is not None:
                self.unset_model(
                    api_model_provider=api_model_provider,
                    params=params,
                    options=options,
                )

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

    # ==============================================================================
    # Private helpers
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
        if type(payload) in [str, tuple]:
            return payload

        for k in CLEAR_PREDEFINED_PARAMS:
            payload.pop(k, None)
        # If stream param is not given, then set as False
        payload["stream"] = payload.get("stream", False)
        return payload

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

        return self._guardrail_response_if_needed(response=response)

    @staticmethod
    def _filter_params_to_acceptable(
        api_type: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Filter a request payload so that it contains only the parameters
        accepted by the downstream LLM provider.

        Each provider (e.g. OpenAI) defines a whitelist of keys that it
        understands.  Supplying unknown keys can lead to ``400 Bad Request``
        errors from the external service.  This helper builds a new
        dictionary containing **only** those keys that are part of the
        provider‑specific whitelist.

        Parameters
        ----------
        api_type: str
            Identifier of the target provider (currently ``"openai"`` is
            supported).  An unknown ``api_type`` raises an :class:`Exception`.

        params: Dict[str, Any]
            The original request payload supplied by the client.  It may
            contain arbitrary keys.

        Returns
        -------
        Dict[str, Any]
            A dictionary with the subset of ``params`` that are listed in
            :data:`OPENAI_ACCEPTABLE_PARAMS` when ``api_type`` is
            ``"openai"``.  Keys not in the whitelist are omitted.

        Raises
        ------
        Exception
            If ``api_type`` is not recognised.

        Notes
        -----
        The input ``params`` mapping is **not** mutated; a fresh dictionary
        ``_params`` is constructed and returned.  This makes the function
        safe to use in logging or audit trails where the original payload
        must remain unchanged.
        """
        _params = {}
        if api_type == "openai":
            for p in OPENAI_ACCEPTABLE_PARAMS:
                if p in params:
                    _params[p] = params[p]
        else:
            raise Exception(f"Unsupported API type: {api_type}")
        return _params

    @staticmethod
    def _prepare_params_for_provider(
        params: Optional[Dict[str, Any]], model_provider: ApiModel
    ) -> Optional[Dict[str, Any]]:
        """
        Adjust the payload according to the capabilities of the selected
        ``model_provider``.

        Some providers (e.g. OpenAI) support *tool* / *function* calling via the
        ``tools`` and ``functions`` keys.  If the chosen ``model_provider``
        does **not** have ``tool_calling`` enabled, those keys must be
        stripped to avoid validation errors from the downstream API.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            The payload that will be sent to the downstream model.  May be
            ``None`` if the endpoint does not require a request body.

        model_provider : ApiModel
            The concrete model configuration object.  Its ``tool_calling``
            attribute indicates whether tool/function specifications are
            expected by the provider.

        Returns
        -------
        Optional[Dict[str, Any]]
            The (potentially mutated) ``params`` dictionary.  If either
            ``params`` or ``model_provider`` is ``None`` the original value
            is returned unchanged.

        Notes
        -----
        The function mutates ``params`` *in‑place* for efficiency; callers
        should treat the returned mapping as the definitive payload to be
        forwarded.
        """
        if model_provider is None or params is None:
            return params

        if not model_provider.tool_calling:
            for _fc in ["tools", "functions"]:
                params.pop(_fc, None)

        return params

    def _resolve_stream_type(self, api_model_provider: ApiModel):
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

        return is_generic_to_ollama, is_ollama_to_generic, is_ollama
