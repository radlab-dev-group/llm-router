"""
AnonymizeText endpoint.

This module defines the :class:`AnonymizeText` Flask‑compatible endpoint
that receives a JSON payload containing a ``text`` field, applies the full
set of built‑in anonymisation rules, and returns the anonymised text.
The endpoint inherits from
:class:`~llm_router_api.endpoints.endpoint_i.EndpointWithHttpRequestI`,
leveraging the generic request‑handling logic while disabling most of the
proxy‑related behaviour (``direct_return=True``).

Typical usage (via the ``@EP`` decorator)::

    POST /anonymize_text
    {
        "text": "User's phone is 555‑123‑4567 and email john@example.com"
    }

Response::

    {
        "anonymized_text": "User's phone is <PHONE> and email <EMAIL>"
    }
"""

from typing import Optional, Dict, Any


from llm_router_lib.anonymizer.core import Anonymizer

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.base.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL

from llm_router_lib.data_models.anonymizer import AnonymizerModel
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


class AnonymizeText(EndpointWithHttpRequestI):
    """
    Endpoint that anonymises a plain‑text string using the library's default
    rule set.

    The endpoint does **not** require any specific request parameters
    (``REQUIRED_ARGS`` and ``OPTIONAL_ARGS`` are set to ``None``) because
    it only expects a single ``text`` field inside the JSON body.  The
    ``direct_return`` flag is enabled so the processed payload is returned
    directly to the client without additional wrapping.
    """

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
        """
        Initialise the ``anonymize_text`` endpoint.

        Parameters
        ----------
        logger_file_name : str | None, optional
            Destination file for log records.  If ``None`` the default
            ``llm-router.log`` is used.
        logger_level : str | None, optional
            Logging verbosity (e.g. ``"INFO"``, ``"DEBUG"``).  Defaults to the
            library‑wide ``REST_API_LOG_LEVEL``.
        prompt_handler : PromptHandler | None, optional
            Not used by this endpoint but required by the base class.
        model_handler : ModelHandler | None, optional
            Not used by this endpoint but required by the base class.
        ep_name : str, optional
            URL fragment that identifies the endpoint; defaults to
            ``"anonymize_text"``.
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
            direct_return=True,
        )

        # Initialise a dedicated Anonymizer instance with the full rule set.
        self._anonymizer = Anonymizer(rules=Anonymizer.ALL_ANONYMIZER_RULES)

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate the incoming request and build the response payload.

        The ``@EP.require_params`` decorator ensures that the request body is
        parsed into a dictionary before this method runs.  The method wraps
        the raw ``text`` value in an :class:`AnonymizerModel` (which provides
        type‑checking) and then returns a dictionary containing the
        anonymised result under the key ``"anonymized_text"``.

        Parameters
        ----------
        params : dict | None
            Parsed JSON payload from the client.  Expected to contain a
            ``"text"`` key; missing keys will raise a validation error
            earlier in the request pipeline.

        Returns
        -------
        dict
            ``{"anonymized_text": <result>}`` where ``<result>`` is the
            anonymised version of the input text.
        """
        options = AnonymizerModel(**params)
        return {"anonymized_text": self._do_text_anonymization(text=options.text)}

    def _do_text_anonymization(self, text: str) -> str:
        """
        Apply the configured anonymisation rules to *text*.

        This thin wrapper exists to keep the public ``prepare_payload`` method
        focused on request handling while delegating the actual text processing
        to the :class:`Anonymizer` instance created during construction.

        Parameters
        ----------
        text : str
            The raw input string supplied by the client.

        Returns
        -------
        str
            The anonymised text, with any detected personal data replaced
            by placeholder tokens defined by the active rule set.
        """
        return self._anonymizer.anonymize(text=text)
