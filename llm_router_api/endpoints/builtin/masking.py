"""
FastTextMasking endpoint.

This module defines the :class:`FastTextMasking` Flask‑compatible endpoint
that receives a JSON payload containing a ``text`` field, applies the full
set of built‑in masking rules, and returns the masked text.
The endpoint inherits from
:class:`~llm_router_api.endpoints.endpoint_i.EndpointWithHttpRequestI`,
leveraging the generic request‑handling logic while disabling most of the
proxy‑related behaviour (``direct_return=True``).

Typical usage (via the ``@EP`` decorator)::

    POST /fast_text_mask
    {
        "text": "User's phone is 555‑123‑4567 and email john@example.com"
    }

Response::

    {
        "text": "User's phone is <PHONE> and email <EMAIL>"
    }
"""

from typing import Optional, Dict, Any


from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.base.model_handler import ModelHandler
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI
from llm_router_api.base.constants import (
    REST_API_LOG_LEVEL,
    ENABLE_GENAI_ANONYMIZE_TEXT_EP,
)

from llm_router_plugins.maskers.fast_masker.core.masker import FastMasker
from llm_router_lib.data_models.masker import FastMaskerModel, GenAIAnonymizerModel


class FastTextMasking(EndpointWithHttpRequestI):
    """
    Endpoint that masks a plain‑text string using the library's default
    rule set.

    The endpoint does **not** require any specific request parameters
    (``REQUIRED_ARGS`` and ``OPTIONAL_ARGS`` are set to ``None``) because
    it only expects a single ``text`` field inside the JSON body.  The
    ``direct_return`` flag is enabled so the processed payload is returned
    directly to the client without additional wrapping.
    """

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = True

    REQUIRED_ARGS = ["text"]
    OPTIONAL_ARGS = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "fast_text_mask",
    ):
        """
        Initialise the ``fast_text_mask`` endpoint.

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
            ``"fast_text_mask"``.
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

        self._fast_masker = FastMasker(rules=FastMasker.ALL_MASKER_RULES)

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate the incoming request and build the response payload.

        The ``@EP.require_params`` decorator ensures that the request body is
        parsed into a dictionary before this method runs.  The method wraps
        the raw ``text`` value in an :class:`FastMaskerModel` (which provides
        type‑checking) and then returns a dictionary containing the
        masked result under the key ``"text"``.

        Parameters
        ----------
        params : dict | None
            Parsed JSON payload from the client.  Expected to contain a
            ``"text"`` key; missing keys will raise a validation error
            earlier in the request pipeline.

        Returns
        -------
        dict
            ``{"text": <result>}`` where ``<result>`` is the
            masked version of the input text.
        """
        options = FastMaskerModel(**params)
        return {"text": self._fast_masker.mask_text(text=options.text)}


if ENABLE_GENAI_ANONYMIZE_TEXT_EP:

    class GenAIModelMasking(EndpointWithHttpRequestI):
        REQUIRED_ARGS = ["model_name", "text"]
        OPTIONAL_ARGS = None

        SYSTEM_PROMPT_NAME = {
            "pl": "builtin/system/pl/anonymize-text",
            "en": "builtin/system/en/anonymize-text",
        }

        def __init__(
            self,
            logger_file_name: Optional[str] = None,
            logger_level: Optional[str] = REST_API_LOG_LEVEL,
            prompt_handler: Optional[PromptHandler] = None,
            model_handler: Optional[ModelHandler] = None,
            ep_name: str = "anonymize_text_genai",
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
                direct_return=False,
            )

            self._prepare_response_function = self.__prepare_response_function

        @EP.require_params
        def prepare_payload(
            self, params: Optional[Dict[str, Any]]
        ) -> Optional[Dict[str, Any]]:
            options = GenAIAnonymizerModel(**params)
            _payload = options.model_dump()

            _payload["model"] = _payload["model_name"]
            _payload["stream"] = _payload.get("stream", False)
            _payload["messages"] = [
                {
                    "role": "user",
                    "content": _payload["text"],
                }
            ]
            _payload.pop("text")

            return _payload

        def __prepare_response_function(self, response):
            _, _, assistant_response = self._get_choices_from_response(
                response=response
            )
            return {"text": assistant_response}
