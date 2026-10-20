"""
Azure OpenAI API integration utilities.

The module provides **AzureOpenAiType**, a concrete implementation of
:class:`llm_router_api.core.api_types.types_i.ApiTypesI`.

Unlike Vertex AI (Gemini) or Bedrock (Converse), the Azure OpenAI wire
protocol **is** OpenAI‑compatible: request and response bodies, including
``tool_calls`` and the SSE stream framing, are the OpenAI ones.  What makes
Azure a provider of its own is how the model is addressed and how the call
is authenticated:

* the model lives in the **URL** as a *deployment name*
  (``/openai/deployments/{deployment}/chat/completions``),
* every data‑plane call must carry the **``api-version`` query parameter**
  (the service is versioned per‑call, ``YYYY-MM-DD``),
* authentication is the Azure‑specific **``api-key`` header** (API keys) or a
  **``Bearer`` Microsoft Entra ID token** (``Authorization``).

So the type overrides only the request adapter hooks that differ from the
historical OpenAI behaviour — :meth:`request_path` (deployment path +
``api-version``) and :meth:`request_headers` (``api-key`` / Entra bearer) —
and inherits the OpenAI‑style :meth:`request_body` (model/deployment
injection and system‑message prepend) unchanged.  Streaming needs no
dedicated conversion: Azure streams plain ``text/event-stream`` SSE with the
OpenAI chunk shape and the ``data: [DONE]`` sentinel, which the router's
OpenAI passthrough forwards as is.

Entra ID token resolution (client credentials, workload identity, managed
identity) lives in :mod:`llm_router_api.core.api_types.auth.azure` and needs
no extra dependency — ``requests`` is already a hard requirement.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import quote

from llm_router_api.core.api_types.auth.azure import AzureAdTokenProvider
from llm_router_api.core.api_types.types_i import ApiTypesI

logger = logging.getLogger(__name__)

#: Latest **GA** Azure OpenAI data‑plane inference version used when the
#: operator does not pin one via ``provider_options.api_version``.  The data
#: plane is versioned per call (the ``api-version`` query parameter), so an
#: outdated pin only degrades gracefully — newer operations stay reachable by
#: overriding the option.
DEFAULT_API_VERSION = "2024-10-21"

#: URL styles the Azure data plane offers for the same operations.
STYLE_DEPLOYMENTS = "deployments"
STYLE_V1 = "v1"
_KNOWN_STYLES = (STYLE_DEPLOYMENTS, STYLE_V1)

#: Deployment‑style paths (the default): the deployment name is a path
#: segment, so the request body addresses no model of its own.
CHAT_PATH = "/openai/deployments/{deployment}/chat/completions"
EMBEDDINGS_PATH = "/openai/deployments/{deployment}/embeddings"

#: The ``/openai/v1`` style serves the same operations with the model taken
#: from the request body instead of the path.
V1_CHAT_PATH = "/openai/v1/chat/completions"
V1_EMBEDDINGS_PATH = "/openai/v1/embeddings"

#: The Responses API only exists under ``/openai/v1``, in both styles.
RESPONSES_PATH = "/openai/v1/responses"

#: Free ``GET`` the resource answers with the models it serves.  The health
#: probe uses it instead of the monitor's generic list (see
#: :meth:`AzureOpenAiType.ping_path`).
MODELS_PATH = "/openai/models"


class AzureOpenAiType(ApiTypesI):
    """
    Concrete descriptor for Azure OpenAI endpoints.

    The wire protocol is OpenAI‑compatible, so only the addressing
    (deployment‑in‑path URLs + ``api-version``) and the authentication
    (``api-key`` header or Microsoft Entra ID bearer token) are provider
    specific; bodies are built by the inherited OpenAI‑style hooks.
    """

    # ------------------------------------------------------------------
    # Endpoint descriptors (deployment‑style, the Azure default)
    # ------------------------------------------------------------------
    def chat_ep(self) -> str:
        """
        Return the deployment‑style chat completions path.
        """
        return CHAT_PATH

    def completions_ep(self) -> str:
        """
        Azure serves completions through the chat completions operation.
        """
        return self.chat_ep()

    def responses_ep(self) -> str:
        """
        The Responses API has no deployment‑style path; it is always
        ``/openai/v1/responses`` with the model in the body.
        """
        return RESPONSES_PATH

    def embeddings_ep(self) -> str:
        """
        Return the deployment‑style embeddings path.
        """
        return EMBEDDINGS_PATH

    # ------------------------------------------------------------------
    # Provider helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _provider_options(provider: Any) -> Dict[str, Any]:
        """
        Return the provider's ``provider_options`` mapping (empty when absent).
        """
        options = ApiTypesI._provider_field(provider, "provider_options", None)
        return dict(options) if isinstance(options, dict) else {}

    @classmethod
    def deployment_name(cls, provider: Any) -> str:
        """
        Return the Azure deployment name the provider addresses.

        Resolution order: ``provider_options.deployment`` (an explicit
        deployment, e.g. when several logical models share one deployment),
        then ``model_path``, then the logical model ``name``.
        """
        options = cls._provider_options(provider)
        for value in (
            options.get("deployment"),
            ApiTypesI._provider_field(provider, "model_path", ""),
            ApiTypesI._provider_field(provider, "name", ""),
        ):
            name = str(value or "").strip()
            if name:
                return name.lstrip("/")
        return ""

    @classmethod
    def api_version(cls, provider: Any) -> str:
        """
        Return the ``api-version`` query value (``provider_options.api_version``
        or the module default).
        """
        options = cls._provider_options(provider)
        return str(options.get("api_version") or DEFAULT_API_VERSION).strip()

    @classmethod
    def _url_style(cls, provider: Any) -> str:
        """
        Return the URL style (``provider_options.api_style``).

        ``deployments`` (the default) puts the deployment name in the path;
        ``v1`` uses the ``/openai/v1/...`` paths with the model in the body.
        An unrecognised value falls back to the default with a warning rather
        than failing the import of a whole configuration.
        """
        options = cls._provider_options(provider)
        style = str(options.get("api_style") or STYLE_DEPLOYMENTS).strip().lower()
        if style not in _KNOWN_STYLES:
            logger.warning(
                "Unknown Azure api_style %r (expected one of %s); "
                "falling back to %r.",
                style,
                ", ".join(_KNOWN_STYLES),
                STYLE_DEPLOYMENTS,
            )
            return STYLE_DEPLOYMENTS
        return style

    # ------------------------------------------------------------------
    # Request adapter hooks
    # ------------------------------------------------------------------
    def request_path(
        self,
        endpoint_url: str,
        provider: Any = None,
        stream: bool = False,
    ) -> str:
        """
        Build the Azure data‑plane path for the requested endpoint, with the
        mandatory ``api-version`` query parameter.

        Streaming shares the chat path: Azure streams the same
        ``chat/completions`` operation as ``text/event-stream`` when the body
        carries ``"stream": true``.
        """
        fragment = (endpoint_url or "").strip("/")
        v1_style = self._url_style(provider) == STYLE_V1
        if "embed" in fragment:
            template = V1_EMBEDDINGS_PATH if v1_style else self.embeddings_ep()
        elif "responses" in fragment:
            template = self.responses_ep()
        else:
            template = V1_CHAT_PATH if v1_style else self.chat_ep()
        return self._with_api_version(template, provider)

    def _with_api_version(self, template: str, provider: Any) -> str:
        """
        Substitute the deployment name into ``template`` (when it carries the
        segment) and append the ``api-version`` query parameter.
        """
        path = template
        if "{deployment}" in template:
            path = template.format(
                deployment=quote(self.deployment_name(provider), safe="")
            )
        return f"{path}?api-version={quote(self.api_version(provider), safe='')}"

    def request_headers(self, provider: Any) -> Dict[str, str]:
        """
        Build the Azure authentication headers for ``provider``.

        Resolution order (first hit wins):

        1. ``api_token`` or ``provider_options.api_key`` – an Azure OpenAI
           API key, sent in the Azure‑specific ``api-key`` header;
        2. ``provider_options.access_token`` – an explicit Microsoft Entra
           ID bearer token (e.g. minted out of band via
           ``az account get-access-token``);
        3. Microsoft Entra ID credentials resolved through
           :class:`~llm_router_api.core.api_types.auth.azure.AzureAdTokenProvider`
           (client credentials, workload identity or managed identity).
        """
        headers: Dict[str, str] = {"Content-Type": "application/json"}

        api_key = str(self._provider_field(provider, "api_token", "") or "").strip()
        if not api_key:
            api_key = str(
                self._provider_options(provider).get("api_key") or ""
            ).strip()
        if api_key:
            headers["api-key"] = api_key
            return headers

        options = self._provider_options(provider)
        explicit_token = str(options.get("access_token") or "").strip()
        if not explicit_token:
            explicit_token = AzureAdTokenProvider.get_token(options)
        if explicit_token:
            headers["Authorization"] = f"Bearer {explicit_token}"
        return headers

    def ping_path(self, provider: Any) -> Optional[str]:
        """
        Return the model‑listing path the monitor probes.

        ``GET /openai/models`` authenticates, proves the resource is
        reachable and costs no tokens — unlike the inference operations,
        which are POST‑only and would bill a completion on every monitor
        cycle.  A provider‑specific path is needed because the generic probe
        list is useless here: an Azure resource answers ``404`` to
        ``/v1/models``, ``/api/version`` and ``/``, which would have the
        monitor report a perfectly healthy deployment as broken.
        """
        return self._with_api_version(MODELS_PATH, provider)

    def on_response_status(self, provider: Any, status_code: int) -> None:
        """
        Evict a cached Microsoft Entra ID token the upstream rejected.

        A ``401``/``403`` answered by a token minted from the provider's
        credentials means the credential went stale (rotated secret, revoked
        assignment); without the eviction every later request replays the
        same rejected token.  Providers authenticated by an API key or an
        explicit ``access_token`` carry nothing the router caches — nothing
        to drop.
        """
        if status_code not in (401, 403):
            return
        if str(self._provider_field(provider, "api_token", "") or "").strip():
            return
        options = self._provider_options(provider)
        if str(options.get("api_key") or "").strip():
            return
        if str(options.get("access_token") or "").strip():
            return
        AzureAdTokenProvider.invalidate(options)
