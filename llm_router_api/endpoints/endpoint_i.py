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

When ``SERVICE_AS_PROXY`` is ``True`,` the endpoint also contains helper
methods for performing outbound HTTP requests to an external service.
"""

import abc
import time
import json
import logging
import datetime

from copy import deepcopy
from typing import Optional, Dict, Any, Iterable, List, Tuple, Callable

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
from llm_router_api.base.constants_base import ALL_PROVIDERS

from llm_router_api.core.errors import sanitize_error_message

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

from llm_router_api.core.api_types.vllm import VLLMConverters
from llm_router_api.core.api_types.anthropic import AnthropicConverters
from llm_router_api.core.api_types.openai import OPENAI_ACCEPTABLE_PARAMS
from llm_router_api.core.api_types.dispatcher import ApiTypesDispatcher, API_TYPES

from llm_router_api.endpoints.httprequest import HttpRequestExecutor


if USE_PROMETHEUS:
    from llm_router_api.core.metrics_handler import MetricsHandler
    from flask import current_app

    try:
        from llm_router_api.core.router_metrics import (
            RouterMetrics as _RouterMetrics,
        )
    except ImportError:
        _RouterMetrics = None  # type: ignore


class SecureEndpointI(abc.ABC):
    """
    Base class that equips an endpoint with security‑related utilities.

    The class centralises common functionality required by all concrete
    endpoints, namely:

    * **Guardrail pipelines** – enforce content‑safety and policy checks on
      incoming requests and outgoing responses.
    * **Masking pipelines** – optionally anonymize or redact sensitive data
      in the payload before it is forwarded to a downstream model.
    * **Auditing helpers** – create start/end audit records when the relevant
      ``*_WITH_AUDIT`` flags are enabled.
    * **Metrics integration** – increment counters for guardrail or masking
      incidents when Prometheus metrics are active.

    Sub‑classes (e.g.: class:`EndpointI` or: class:`EndpointWithHttpRequestI`)
    inherit these capabilities and can focus on business‑logic handling.
    """

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = False

    def __init__(self, ep_name: str, method: str, logger: logging.Logger):
        """
        Initialise the security scaffolding for a single HTTP endpoint.

        Parameters
        ----------
        ep_name : str
            The raw endpoint name (URL fragment) used by Flask to register the
            route.  It is stored as ``self._ep_name`` and later exposed via the
            ``name`` property.
        method : str
            HTTP verb expected by the endpoint – typically ``"GET"`` or
            ``"POST"``.  The value is stored as ``self._ep_method`` and
            accessed through the ``method`` property.
        logger : logging.Logger
            A configured logger that will be used throughout the class for
            debugging, info, warning, and error messages.

        The constructor also:

        * Sets up an optional Prometheus ``MetricsHandler`` when
          ``USE_PROMETHEUS`` is ``True``.
        * Lazily creates masker and guardrail pipelines according to the
          global configuration flags (e.g. ``FORCE_MASKING``,
          ``FORCE_GUARDRAIL_REQUEST``).
        * Instantiates audit‑log helpers when the corresponding ``*_WITH_AUDIT``
          switches are active.

        No return value; the instance is ready for use after construction.
        """
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
        """
        Initialize the :class:`MaskerPipeline` used for payload anonymization.

        This helper lazily creates a ``MaskerPipeline`` instance the first time it
        is required. Subsequent calls are no‑ops, preventing duplicate
        pipeline construction and ensuring that the same pipeline (with the
        same configuration) is reused throughout the request lifecycle.

        Parameters
        ----------
        plugins : List[str]
            Ordered list of plugin identifiers that should be loaded into the
            pipeline. The plugins define the masking strategies (e.g., redaction,
            hashing, tokenization) applied to the payload.

        Returns
        -------
        None
            The method mutates ``self._masker_pipeline`` as a side effect.
        """
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
        """
        Initialize a :class:`GuardrailPipeline` for request or response validation.

        Guardrails enforce policy checks (e.g., profanity filtering, content
        safety, limiting) before a request is forwarded to a downstream
        model or before a response is sent back to the client.  The pipeline is
        created lazily; if it already exists, the method returns immediately.

        Parameters
        ----------
        plugins : List[str]
            List of plugin names that implement individual guardrail checks.
        for_response_mode : bool
            ``True`` creates/uses the response‑side guardrail pipeline,
            ``False`` creates/uses the request‑side pipeline.

        Returns
        -------
        None
            The method mutates ``self._guardrails_pipeline_request`` or
            ``self._guardrails_pipeline_response`` as a side effect.
        """
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
        """
        Create an audit log entry for the start of a guarded or masked operation.

        The method is invoked only when the corresponding ``*_WITH_AUDIT``
        flag is enabled.  It records the endpoint name, the type of audit
        (e.g. ``"guardrail_request"``, ``"masking"``), a timestamp, and a deep
        copy of the initial payload.  The returned dictionary is later passed
        to :meth:`_end_audit_log_if_needed` to finalize the entry.

        Parameters
        ----------
        payload : Any
            The original request payload that will be audited.
        prepare_audit_log : bool
            Flag indicating whether auditing is enabled for this operation.
        audit_type : str
            Identifier describing the audit purpose (e.g. ``"masking"``).

        Returns
        -------
        dict | None
            A dictionary representing the beginning of the audit log, or
            ``None`` if ``prepare_audit_log`` is ``False``.
        """

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
        payload, mappings, audit_log, auditor: AnyRequestAuditor, force_end: bool
    ):
        """
        Finalize an audit log entry and persist it via the provided auditor.

        If an audit log was created by :meth:`_begin_audit_log_if_needed`,
        this method records the ending timestamp and the final payload.
        It then delegates storage to ``auditor.add_log``.  When no audit log
        exists, the call is no‑op unless ``force_end`` is ``True``, in which
        case an exception is raised to indicate a programming error.

        Parameters
        ----------
        payload : Any
            The payload at the end of the operation (may differ from the start).
        audit_log : dict | None
            The dictionary returned by ``_begin_audit_log_if_needed``.
        auditor : AnyRequestAuditor
            Auditor instance responsible for persisting the audit record.
        force_end : bool
            If ``True`` and ``audit_log`` is ``None``, raise an exception.

        Returns
        -------
        None
        """
        if not audit_log:
            if force_end:
                raise RuntimeError("Cannot end audit! Audit log is not set!")
            return

        if force_end or audit_log["begin"]["payload"] != payload:
            audit_log["end"] = {
                "timestamp": datetime.datetime.now().timestamp(),
                "payload": deepcopy(payload),
                "mappings": deepcopy(mappings),
            }
            auditor.add_log(audit_log)

    def _is_request_guardrail_safe(self, payload: Dict):
        """
        Evaluate the request payload against configured guardrail plugins.

        The method short‑circuits when guardrails are globally disabled or when
        no guardrail pipeline has been instantiated.  Otherwise, it runs the
        request‑side ``GuardrailPipeline`` and, if a violation is detected,
        records an audit entry (when enabled) and updates metrics.

        Parameters
        ----------
        payload : Dict
            Normalised request payload to be checked.

        Returns
        -------
        bool
            ``True`` if the payload passes all guardrail checks, ``False`` otherwise.
        """
        if (
            self.EP_DONT_NEED_GUARDRAIL_AND_MASKING
            or not self._guardrails_pipeline_request
            or not self._guardrail_auditor_request
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
                mappings={},
                audit_log=audit_log,
                auditor=self._guardrail_auditor_request,
                force_end=True,
            )

        if not is_safe and self._metrics:
            self._metrics.inc_guardrail_incident()

        return is_safe

    def _do_masking_if_needed(
        self, payload: Dict[str, Any] | None
    ) -> Tuple[Optional[Dict[str, Any]], Dict]:
        """
        Apply masking to the payload when required by configuration or request.

        Masking is performed if ``FORCE_MASKING`` is enabled globally or if the
        incoming payload contains the ``"anonymize": True`` flag.  The method
        creates an audit log (when ``MASKING_WITH_AUDIT`` is ``True``), runs the
        masker pipeline, updates metrics on changes, and finalizes the audit
        entry.

        Parameters
        ----------
        payload : Dict[str, Any]
            The request payload that may need to be anonymized.

        Returns
        -------
        Dict[str, Any]
            The (potentially) masked payload.  If masking is not required,
            the original payload is returned unchanged.
        """
        if (
            self.EP_DONT_NEED_GUARDRAIL_AND_MASKING
            or not payload
            or not isinstance(payload, dict)
        ):
            return payload, {}

        do_masking = FORCE_MASKING or bool(payload.get("anonymize", False))
        if not do_masking:
            return payload, {}

        audit_log = self._begin_audit_log_if_needed(
            payload=payload,
            prepare_audit_log=MASKING_WITH_AUDIT,
            audit_type="masking",
        )
        masked_payload, mappings = self._mask_whole_payload(
            payload=payload,
            algorithms=MASKING_STRATEGY_PIPELINE,
        )

        if masked_payload != payload and self._metrics:
            self._metrics.inc_masker_incident()

        payload = masked_payload

        if self._mask_auditor:
            self._end_audit_log_if_needed(
                payload=payload,
                mappings=mappings,
                audit_log=audit_log,
                auditor=self._mask_auditor,
                force_end=False,
            )

        return payload, mappings

    def _mask_whole_payload(
        self,
        payload: Dict | str | List | Any,
        algorithms: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Dict]:
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
        self._prepare_masker_pipeline(plugins=algorithms or [])
        _p, _m = self._masker_pipeline.apply(payload=payload)
        return _p, _m


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
    """
    Supported HTTP methods for any endpoint.
    """

    REQUIRED_ARGS = []
    """
    Names of parameters that **must** be supplied by the client.
    """

    OPTIONAL_ARGS = []
    """
    Names of parameters that are accepted but not required.
    """

    SYSTEM_PROMPT_NAME = {"pl": None, "en": None}
    """
    Mapping of language codes to system‑prompt identifiers.
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
            Logging level name (``"INFO"``, ``"DEBUG"``, …).  If omitted,
            the library default is used.
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
        if self._ep_types_str is None or not self._ep_types_str:
            raise RuntimeError("Endpoint api type is required!")

        if not set(self._ep_types_str).intersection(set(API_TYPES)):
            raise RuntimeError(f"Supported api types are [{', '.join(API_TYPES)}]!")

        self._api_type_dispatcher = ApiTypesDispatcher()
        self._check_method_is_allowed(method=method)

        # Hook function to prepare response
        self._prepare_response_function: Optional[Callable] = None

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
    def prepare_response_function(self):
        """
        Getter method for retrieving the function responsible for preparing responses.

        It provides access to the internal functionality that processes and returns
        structured response data.

        Returns
        -------
        Callable
            A function that encapsulates the logic for preparing and formatting
            response outputs.
        """
        return self._prepare_response_function

    @property
    def model_handler(self):
        """
        Return the :class:`ModelHandler` instance associated with this endpoint.

        The handler is responsible for resolving model identifiers supplied by
        the client into concrete :class:`ApiModel` objects.  It may be ``None``
        when the endpoint does not interact with a model (e.g., a health check
        endpoint).
        """
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
            registrar.  Maybe ``None`` for endpoints that do not expect
            any input.

        Returns
        -------
        dict | Iterable[bytes] | None
            The concrete result that will be JSON‑encoded (or streamed) back
            to the client.

        Raises
        ------
        NotImplementedError
            Always rise in the base class – concrete subclasses must
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
            A tuple where the first element is a JSON‑serializable dictionary
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
            # Heuristic for plain text (if the body is a string)
            status_code = 404

        error_message = (
            sanitize_error_message(str(body)) if body else "Error while processing"
        )
        is_provider = any(t in self._ep_types_str for t in ALL_PROVIDERS)
        error_body = {
            "error": {
                "message": error_message,
                "type": "api_error" if is_provider else "builtin_error",
                "param": None,
                "code": status_code,
            },
            "status": False,
        }
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
            If the payload does not contain a recognized model key or the
            model name cannot be resolved via ``self._model_handler``.
        """
        # if self.REQUIRED_ARGS is None or not len(self.REQUIRED_ARGS):
        #     return
        model_name = self._model_name_from_params_or_model(params=params)
        if model_name is None:
            raise ValueError(f"model_name cannot be None!")

        if self._model_handler is None:
            raise RuntimeError("Model handler must be initialized!")

        api_model = self._model_handler.get_model_provider(
            model_name=model_name, options=options, fake=fake
        )
        if api_model is None:
            raise ValueError(f"Model '{model_name}' not found in configuration")
        return api_model

    def unset_model(
        self,
        api_model_provider: Optional[ApiModel],
        params: Dict[str, Any],
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Release a previously‑acquired model provider back to the pool.

        This method is a thin wrapper around :meth:`ModelHandler.put_model_provider`
        that ensures the model is correctly deregistered even if the request
        processing raised an exception.

        Parameters
        ----------
        api_model_provider : ApiModel
            The model provider that was previously obtained via
            :meth:`get_model_provider`.
        params : Dict[str, Any]
            The request payload that was used to obtain the model.  It is used to
            re‑derive the model name if necessary.
        options : Optional[Dict[str, Any]], default ``None``
            Additional options that were passed to the model handler when the
            model was fetched.  They are forwarded unchanged to the ``put`` call.
        """
        if not api_model_provider:
            return
        model_name = self._model_name_from_params_or_model(
            params=params, api_model_provider=api_model_provider
        )

        if not model_name or not self._model_handler:
            return

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
        Prepare the util pipeline if it has not been initialized.

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

    def _run_utils_plugins(self, payload: Optional[Dict]):
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
            The payload after all util plugins have been applied, or the
            original payload when no util pipeline is configured.
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
        if not choices:
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
        if params is None or self.REQUIRED_ARGS is None or not self.REQUIRED_ARGS:
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
        elif prompt_name and self._prompt_handler:
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
    def __get_language(params: Dict[str, Any]) -> Optional[str]:
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
        #  * 429 - Too Many Requests (rate limited)
        #  * 503 - Service Unavailable
        #  * 504 - Gateway Timeout
        #  * > 500 - General error
        RETRY_WHEN_STATUS = [429, 503, 504, 500]
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
        and completion endpoints and stores the request timeout.

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

    # ------------------------------------------------------------------
    # Router metrics helpers (no-op safe — silently skipped when disabled)
    # ------------------------------------------------------------------
    def _get_router_metrics(self):
        """
        Return the ``RouterMetrics`` instance from Flask extensions.

        Uses lazy caching so that repeated calls during a single request do not
        repeatedly hit Flask's application context.  Returns ``None`` gracefully
        when outside a request context or Prometheus is disabled.
        """
        if getattr(self, "__rm_cache", None) is None:
            self._rm_caching = True
            try:
                ext = getattr(current_app, "extensions", {})
                if isinstance(ext, dict):
                    val = ext.get("router_metrics")
                    if val is not None:
                        self._rm_caching = val
                        return val
            except RuntimeError:
                pass  # outside request context
            self._rm_cache = None
        return self._rm_cache

    def _record_provider_latency(self, start_ns: float) -> Optional[float]:
        """
        Measure and record provider latency; returns elapsed seconds or ``None``.
        """
        rm = self._get_router_metrics()
        if rm is None:
            return None
        elapsed = time.time() - start_ns
        self.logger.debug("[metrics] provider_latency=%.4f s", elapsed)
        return elapsed

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

        The method first normalizes the incoming parameters via
        :meth:`prepare_payload`.  When ``self.direct_return`` is set, the
        normalized payload is returned verbatim.  Otherwise, the method
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
            Either a normal JSON‑serializable dictionary, a streaming NDJSON
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
        self.logger.debug(
            f"[{self._ep_method}] {self._ep_name} => {self._ep_types_str}"
        )

        self._start_time = time.time()
        try:
            # ------------ BEGIN SECTION
            # 0.0 There user is able to prepare a payload to process
            params = self.prepare_payload(params)
            # 0.1 Run util plugins which may modify the user context
            params = self._run_utils_plugins(payload=params)
            # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

            # ------------ BEGIN SECURE SECTION ------------
            # 1. Check payload using guardrails
            if not self._is_request_guardrail_safe(payload=params):
                if use_streaming:
                    api_model_provider = self.get_model_provider(
                        params=params, options=options, fake=True
                    )

                    stream_type = (
                        self._http_executor.stream_handler.resolve_stream_type(
                            endpoint_ep_types=self._ep_types_str,
                            api_model_provider=api_model_provider,
                        )
                    )

                    return self._http_executor.stream_response(
                        ep_url="",
                        params=params,
                        options=options,
                        stream_type=stream_type,
                        api_model_provider=api_model_provider,
                        force_text="Content blocked by guardrail. "
                        "Reason: Not safe content!",
                    )

                return self.return_response_not_ok(
                    body={"reason": "guardrail", "error": "Not safe content!"}
                )

            # 2. Mask the whole payload if needed
            params, mappings = self._do_masking_if_needed(payload=params)

            # ...and show existing mappings
            self.logger.debug(
                "Masking mappings: %s",
                json.dumps(mappings, indent=2, ensure_ascii=False),
            )

            # 3. Clear payload to accept only required params
            params = self._clear_payload(payload=params)
            # ------------ END SECURE SECTION ------------

            # 4. Endpoint processing
            map_prompt = None
            prompt_str_force = None
            prompt_str_postfix = None
            if isinstance(params, dict):
                map_prompt = params.pop("map_prompt", {})
                prompt_str_force = params.pop("prompt_str_force", "")
                prompt_str_postfix = params.pop("prompt_str_postfix", "")

            # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

            if self.direct_return:
                return params

            # In case when the endpoint type is the same as a model endpoint type,
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
                raise ValueError(f"API model isn't found in params {params}")

            # ---- Prometheus: record provider & pipeline stage --------------------
            rm = self._get_router_metrics()
            if rm is not None and api_model_provider is not None:
                try:
                    rm.record_pipeline_stage("provider_resolved", "success")
                    rm.record_provider_call(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # metrics must never break the request

            # Modify params specified for the chosen provider
            params = self._prepare_params_for_provider(
                params=params, model_provider=api_model_provider
            )
            params = self._ensure_alternating_roles(params=params)
            # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

            clear_chosen_provider_finally = True

            self.logger.debug(
                f"Request model {api_model_provider.name} "
                f"with config id: {api_model_provider.id} "
                f"[{api_model_provider.api_type}: {api_model_provider.api_host}]"
            )

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
                    prompt_str=prompt_str or "",
                    orig_params=orig_params,
                    params=params,
                    options=options or {},
                    reconnect_number=reconnect_number or 0,
                )

            if prompt_name is not None:
                self.logger.debug(f" -> prompt_name: {prompt_name}")
                self.logger.debug(f" -> prompt_str: {str(prompt_str)[:40]}...")

            if api_model_provider.api_type in ["openai"]:
                params = self._filter_params_to_acceptable(
                    api_type=api_model_provider.api_type, params=params
                )

            # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

            if use_streaming:
                clear_chosen_provider_finally = False
                if self._call_for_each_user_msg:
                    raise ValueError(
                        "Streaming is available only for single message"
                    )

                # ---- Prometheus: response format (streamed) -------------------
                rm_fmt = self._get_router_metrics()
                if rm_fmt is not None and api_model_provider is not None:
                    try:
                        rm_fmt.record_response_format(
                            fmt="streamed",
                            model_name=api_model_provider.name,
                            provider_type=api_model_provider.api_type,
                        )
                    except Exception:  # pylint: disable=broad-exception-caught
                        pass

                stream_type = self._http_executor.stream_handler.resolve_stream_type(
                    endpoint_ep_types=self._ep_types_str,
                    api_model_provider=api_model_provider,
                )

                return self._http_executor.stream_response(
                    ep_url=ep_url,
                    params=params,
                    options=options,
                    stream_type=stream_type,
                    api_model_provider=api_model_provider,
                )

            # ---- Prometheus: response format (non_streamed) ----------------
            rm_ns = self._get_router_metrics()
            if rm_ns is not None and api_model_provider is not None:
                try:
                    rm_ns.record_response_format(
                        fmt="non_streamed",
                        model_name=api_model_provider.name,
                        provider_type=api_model_provider.api_type,
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

            return self._return_response_or_rerun(
                api_model_provider=api_model_provider,
                ep_url=ep_url,
                prompt_str=prompt_str or "",
                orig_params=orig_params,
                params=params,
                options=options or {},
                reconnect_number=reconnect_number or 0,
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

    def return_http_response(
        self, response, api_model_provider: Optional[ApiModel] = None
    ):
        """
        Normalize an HTTP response object into a Python dictionary.

        If the response status code indicates an error, a
        :class:`RuntimeError` is raised with the provider ID.
        When the body cannot be parsed as JSON, a ``{"raw_response": <text>}``
        mapping is returned instead.

        Parameters
        ----------
        response:
            ``requests.Response`` object obtained from a ``GET`` or ``POST``
            call.
        api_model_provider:
            Optional provider metadata used in error messages (never leaked
            to the client in raw form — only the non-sensitive ``.id`` field
            is used).

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
            provider_id = api_model_provider.id if api_model_provider else "unknown"
            self.logger.error(
                "Provider [%s] HTTP %d — response body: %s",
                provider_id,
                response.status_code,
                response.text,
            )
            raise RuntimeError(
                f"Provider {provider_id} returned HTTP {response.status_code}"
            )
        try:
            if self._prepare_response_function is not None:
                result = self._prepare_response_function(response)
                return result
            return response.json()
        except json.JSONDecodeError:
            provider_id = api_model_provider.id if api_model_provider else "unknown"
            self.logger.error(
                "Provider [%s] response is not valid JSON — body: %s",
                provider_id,
                response.text,
            )
            return {"raw_response": response.text}

    # ==============================================================================
    # Private helpers
    @staticmethod
    def _clear_payload(payload: Dict[str, Any] | None):
        """
        Remove internal‑only keys from the payload before it is sent to the
        downstream model.

        Currently, the method strips the ``response_time`` key, which is used
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
        if type(payload) in [str, tuple] or not payload:
            return payload

        for k in CLEAR_PREDEFINED_PARAMS:
            payload.pop(k, None)

        # If stream param is not given, then set as False
        payload["stream"] = payload.get("stream", False)
        return payload

    @classmethod
    def _ensure_alternating_roles(
        cls, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Normalize a ``messages`` payload for compatibility with any
        service that expects a ``system`` → ``user`` → ``assistant``
        alternating sequence.

        Consecutive messages of the same role are merged into a single
        message (their contents are joined), e.g.::

            [system, system, user, user, user]
                -> [system, user]

        Additional fixes applied:

        * every ``system`` message is moved to the front and folded into
          a single ``system`` message;
        * if the first dialogue message is an ``assistant`` one, an empty
          ``user`` placeholder is prepended;
        * if the last message is an ``assistant`` one, an empty ``user``
          placeholder is appended (a chat completion request must end
          with a ``user`` turn).

        Well‑formed payloads are detected in a single pass and returned
        untouched (no copying), so the common case costs almost nothing.

        Parameters
        ----------
        params:
            Request payload possibly containing a ``messages`` list.

        Returns
        -------
        dict
            The possibly‑modified payload with a correctly ordered
            ``messages`` list.
        """
        if not params or "messages" not in params:
            return params

        messages = params["messages"]
        if not isinstance(messages, list) or len(messages) <= 1:
            return params

        if cls._messages_need_fix(messages):
            params["messages"] = cls._build_alternating_messages(messages)
        return params

    @staticmethod
    def _messages_need_fix(messages: List[Any]) -> bool:
        """
        Check whether the *messages* list requires normalisation.

        The check scans the list in a single pass (with early exit) and
        detects any condition that :meth:`_build_alternating_messages` would
        change:

        * more than one ``system`` message (they are folded into one);
        * a ``system`` message which is not the very first entry
          (it is moved to the front);
        * two consecutive dialogue messages with the same role (they are
          merged);
        * a dialogue that does not start with a ``user`` turn (an empty
          ``user`` placeholder is prepended);
        * a dialogue that ends with an ``assistant`` turn (an empty
          ``user`` placeholder is appended).

        Non‑message entries (non‑dicts or dicts without a ``role``) act as
        separators in the dialogue sequence, exactly as during the rebuild.

        Parameters
        ----------
        messages:
            The raw ``messages`` list extracted from the request payload.

        Returns
        -------
        bool
            ``True`` when the list has to be rebuilt, ``False`` when it
            already follows the expected ``system`` → alternating dialogue
            pattern and can be returned untouched.
        """
        first = messages[0]
        last = messages[-1]

        system_count = 0
        prev_role: Optional[str] = None
        for msg in messages:
            role = msg.get("role") if isinstance(msg, dict) else None
            if role == "system":
                system_count += 1
                if system_count > 1:
                    return True
                continue
            if role is None:
                # Non‑message entries break the dialogue sequence.
                prev_role = None
                continue
            if role == prev_role:
                return True
            prev_role = role

        # A single system message is allowed, but only as the first entry.
        if system_count == 1 and not (
            isinstance(first, dict) and first.get("role") == "system"
        ):
            return True

        # Without a leading system, the dialogue must start with a user turn.
        if (
            system_count == 0
            and isinstance(first, dict)
            and first.get("role") not in (None, "user")
        ):
            return True

        # The dialogue must not end with an assistant turn.
        if isinstance(last, dict) and last.get("role") == "assistant":
            return True

        return False

    @classmethod
    def _build_alternating_messages(cls, messages: List[Any]) -> List[Dict]:
        """
        Rebuild the *messages* list so that it starts with a single folded
        ``system`` message followed by a strictly alternating dialogue.

        The rebuild is performed in a single pass: ``system`` messages are
        folded into one at the front, consecutive dialogue messages of the
        same role are merged, and empty ``user`` placeholders are inserted
        so that the dialogue starts and ends with a ``user`` turn.

        Every message dict that may later be mutated is shallow‑copied
        first, so the caller's original dicts are never touched.  This
        matters because the retry path re‑runs this normalisation on the
        same payload and in‑place mutations would merge contents twice.

        Parameters
        ----------
        messages:
            The raw ``messages`` list extracted from the request payload.

        Returns
        -------
        List[Dict]
            A new, correctly ordered list of messages.
        """
        new_messages: List[Dict[str, Any]] = []
        system_msg: Optional[Dict[str, Any]] = None
        last: Any = None  # last appended dialogue entry (always a fresh copy)

        for msg in messages:
            role = msg.get("role") if isinstance(msg, dict) else None
            if role == "system":
                if system_msg is None:
                    system_msg = dict(msg)
                else:
                    system_msg["content"] = cls._merge_message_contents(
                        system_msg.get("content"), msg.get("content")
                    )
            elif (
                role is not None
                and last is not None
                and isinstance(last, dict)
                and last.get("role") == role
            ):
                last["content"] = cls._merge_message_contents(
                    last.get("content"), msg.get("content")
                )
            else:
                new_messages.append(dict(msg) if isinstance(msg, dict) else msg)
                last = new_messages[-1]

        if system_msg is not None:
            new_messages.insert(0, system_msg)

        # The dialogue must start with a user message.
        first = new_messages[0]
        if isinstance(first, dict) and first.get("role") not in (
            None,
            "system",
            "user",
        ):
            new_messages.insert(0, {"role": "user", "content": ""})

        # The dialogue must end with a user message.
        last_entry = new_messages[-1]
        if isinstance(last_entry, dict) and last_entry.get("role") == "assistant":
            new_messages.append({"role": "user", "content": ""})

        return new_messages

    @staticmethod
    def _merge_message_contents(content_a: Any, content_b: Any) -> Any:
        """
        Join the contents of two messages into a single content value.

        String contents are joined with a blank line.  List contents
        (multimodal payloads) are concatenated into one list.
        """
        if content_a is None:
            return content_b
        if content_b is None:
            return content_a
        if isinstance(content_a, list) or isinstance(content_b, list):
            parts_a = (
                content_a
                if isinstance(content_a, list)
                else [{"type": "text", "text": content_a}]
            )
            parts_b = (
                content_b
                if isinstance(content_b, list)
                else [{"type": "text", "text": content_b}]
            )
            return parts_a + parts_b
        text_a = str(content_a)
        text_b = str(content_b)
        if not text_a:
            return text_b
        if not text_b:
            return text_a
        return f"{text_a}\n\n{text_b}"

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
        error_exc = None
        provider_latency_start = (
            time.time()
        )  # ---- Prometheus: latency timer -----------

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
            error_exc = e

        # ---- Prometheus: record provider latency & error on exception ---------------
        rm_err = self._get_router_metrics()
        if rm_err is not None and api_model_provider is not None:
            try:
                elapsed = time.time() - provider_latency_start
                rm_err.record_provider_latency(
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=elapsed,
                )
                if error_exc is not None:
                    # Classify the error code for connection-level failures
                    err_msg = str(error_exc).lower()
                    if "timeout" in err_msg:
                        rm_err.record_provider_error(
                            provider_type=api_model_provider.api_type,
                            model_name=api_model_provider.name,
                            error_code="timeout",
                        )
                    else:
                        rm_err.record_provider_error(
                            provider_type=api_model_provider.api_type,
                            model_name=api_model_provider.name,
                            error_code="connection_error",
                        )
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # metrics must never break the request

        self.unset_model(
            api_model_provider=api_model_provider, params=params, options=options
        )

        # If the HTTP call failed completely, report the error instead of silently
        # returning ``None`` (which Flask would convert to ``{}`` with HTTP 200).
        if error_exc is not None:
            return self.return_response_not_ok(error_exc)

        status_code = None
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

            # ---- Prometheus: retry metrics ----------------------------
            if (
                status_code != 200
                and rm_err is not None
                and api_model_provider is not None
            ):
                try:
                    rm_err.record_provider_latency(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                        seconds=time.time() - provider_latency_start,
                    )
                    rm_err.record_provider_error(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                        error_code=str(status_code),
                    )
                    if reconnect_number < self.RetryResponse.MAX_RECONNECTIONS:
                        rm_err.record_retry(
                            model_name=api_model_provider.name,
                            error_code=str(status_code),
                        )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

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
            # ---- Prometheus: retry exhausted (all retries failed) --------
            if rm_err is not None and api_model_provider is not None:
                try:
                    rm_err.record_retry_exhausted(
                        model_name=api_model_provider.name,
                        last_error_code=str(status_code),
                    )
                    rm_err.record_provider_latency(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                        seconds=time.time() - provider_latency_start,
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
            return response

        # ---- Prometheus: successful provider call ------------------------
        if rm_err is not None and api_model_provider is not None:
            try:
                rm_err.record_provider_latency(
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=time.time() - provider_latency_start,
                )
                # Try to extract token usage from response body (OpenAI / Ollama format)
                if isinstance(response, dict):
                    usage = response.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")
                    if prompt_tokens:
                        rm_err.record_tokens(
                            model_name=api_model_provider.name,
                            direction="input",
                            count=prompt_tokens,
                            provider_type=api_model_provider.api_type,
                        )
                    if completion_tokens:
                        rm_err.record_tokens(
                            model_name=api_model_provider.name,
                            direction="output",
                            count=completion_tokens,
                            provider_type=api_model_provider.api_type,
                        )
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # metrics must never break the request

        return response

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
            A dictionary with the subset of ``params`` that is listed in
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
            raise ValueError(f"Unsupported API type: {api_type}")
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
        if model_provider is None or params is None or not isinstance(params, dict):
            return params

        if not model_provider.tool_calling:
            for _fc in ["tools", "functions"]:
                params.pop(_fc, None)

        if model_provider.api_type in ["vllm"]:
            params = VLLMConverters.Payload.convert_payload(params)

        if model_provider.api_type == "anthropic":
            params = AnthropicConverters.Payload.convert_payload(params)

        return params
