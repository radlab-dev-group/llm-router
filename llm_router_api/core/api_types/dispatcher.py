"""
llm_router_api.core.api_types.dispatcher
=======================================

A thin façade that maps a **string identifier of an external LLM API** (e.g.
``"openai"``, ``"ollama"``, ``"vllm"``) to the concrete implementation that
knows how to build endpoint URLs, HTTP verbs and request payloads for that
backend.

The dispatcher is used by the endpoint layer (`EndpointI` /
`EndpointWithHttpRequestI`) to stay agnostic of the concrete API‑type
implementation.  Adding a new backend only requires:

1. creating a class that implements the
  :class:`~llm_router_api.core.api_types.types_i.ApiTypesI` interface, and
2. registering that class in the ``_REGISTRY`` dictionary below.

All methods are ``@classmethod``s so they can be called without instantiating the
dispatcher itself.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Type

from llm_router_api.core.api_types.types_i import ApiTypesI

from llm_router_api.core.api_types.vllm import VllmType
from llm_router_api.core.api_types.ollama import OllamaType
from llm_router_api.core.api_types.openai import OpenAIApiType
from llm_router_api.core.api_types.llamacpp import LLamaCPPApiType
from llm_router_api.core.api_types.lmstudio import LMStudioApiType
from llm_router_api.core.api_types.anthropic import AnthropicType
from llm_router_api.core.api_types.vertex_ai import VertexAiType
from llm_router_api.core.api_types.bedrock import BedrockType

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------
# Public constant – the full list of API‑type identifiers recognised by the library.
# ----------------------------------------------------------------------------------
API_TYPES = [
    "builtin",
    "openai",
    "ollama",
    "lmstudio",
    "vllm",
    "anthropic",
    "vertex_ai",
    "bedrock",
]


class ApiTypesDispatcher:
    """
    Dispatcher for concrete ``ApiTypesI`` implementations.

    The class does **not** store any state – it only contains a registry that
    maps a normalized ``api_type`` string to the concrete class that implements
    the :class:`~llm_router_api.core.api_types.types_i.ApiTypesI` protocol.

    Every public method mirrors a method of ``ApiTypesI`` but adds a required
    ``api_type`` argument.  The method resolves the appropriate implementation,
    instantiates it, and forwards the call.

    Example
    -------
    >>> ApiTypesDispatcher.models_list_ep("openai")
    '/v1/models'

    The dispatcher raises a :class:`ValueError` if an unknown ``api_type`` is
    supplied.
    """

    # -----------------------------------------------------------------------
    # Registry of concrete implementations.
    # Keys are lower‑cased API‑type identifiers; values are the classes that
    # implement ``ApiTypesI`` for that backend.
    # -----------------------------------------------------------------------
    _REGISTRY: Dict[str, Type[ApiTypesI]] = {
        "ollama": OllamaType,
        "llama.cpp": LLamaCPPApiType,
        "vllm": VllmType,
        "openai": OpenAIApiType,
        "lmstudio": LMStudioApiType,
        "anthropic": AnthropicType,
        "vertex_ai": VertexAiType,
        "bedrock": BedrockType,
    }

    # -----------------------------------------------------------------------
    # Internal helper – resolve a string identifier to an instantiated
    # implementation of ``ApiTypesI``.
    # -----------------------------------------------------------------------
    @classmethod
    def _get_impl(cls, api_type: str) -> ApiTypesI:
        """
        Resolve ``api_type`` to a concrete ``ApiTypesI`` instance.

        Parameters
        ----------
        api_type : str
            Identifier of the external API.  The lookup is case‑insensitive and
            ignores surrounding whitespace.

        Returns
        -------
        ApiTypesI
            An **instance** (not the class) of the concrete implementation
            matching ``api_type``.

        Raises
        ------
        ValueError
            If ``api_type`` is ``None``, empty, or not present in the internal
            ``_REGISTRY``.  The error message lists the supported identifiers.
        """
        key = (api_type or "").strip().lower()
        impl = cls._REGISTRY.get(key)
        if impl is None:
            supported = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(
                f"Unsupported api_type '{api_type}'. Supported: {supported}"
            )
        return impl()

    @classmethod
    def get_proper_endpoint(
        cls,
        api_type: str,
        endpoint_url: str,
        provider: Any = None,
        stream: bool = False,
    ) -> str:
        """
        Resolve a raw endpoint fragment to the canonical endpoint path for the
        specified ``api_type``.

        The resolution is delegated to the concrete type's
        ``request_path`` hook; the default hook inspects ``endpoint_url``
        (after stripping leading/trailing ``/`` characters) for known
        keywords and forwards the request to the appropriate endpoint
        descriptor.

        Parameters
        ----------
        api_type : str
            Identifier of the external LLM API (e.g. ``"openai"``, ``"ollama"``,
            ``"vllm"``).  The lookup is case‑insensitive and ignores surrounding
            whitespace; an unknown identifier raises :class:`ValueError`.

        endpoint_url : str
            A raw URL fragment that may contain one of the following substrings:

            * ``"completions"`` – selects the *completions* endpoint.
            * ``"responses"``   – selects the *responses* endpoint.
            * ``"embeddings"``  – selects the *embeddings* endpoint.
            * otherwise – defaults to the *chat* endpoint.

            Leading and trailing ``/`` characters are removed before the check.

        provider : Any
            Optional provider descriptor (``ApiModel`` or a configuration
            mapping); types whose backend path depends on the provider
            (e.g. Vertex AI) use it to build the resource path.

        stream : bool
            Whether the request is a streaming one; types with a separate
            streaming operation (e.g. Vertex AI) select it accordingly.

        Returns
        -------
        str
            The canonical endpoint path for ``api_type`` (e.g. ``"/v1/completions"``,
            ``"/api/chat"``, etc.).  The returned string does **not** include the
            host or version prefix; it is the path that the backend client will
            append to its base URL.

        Raises
        ------
        ValueError
            If ``api_type`` is ``None``, empty, or not present in the internal
            ``_REGISTRY``.  The error message lists the supported identifiers.

        Notes
        -----
        * Keyword check order (default hook): ``"completions"``, then
          ``"responses"``, then ``"embed"``, then ``"messages"``, fallback
          to ``chat``.  If multiple appear, the first one in the check
          order wins.
        * This method is a thin wrapper around the ``request_path`` hook of
          the concrete ``ApiTypesI`` implementation (whose default mirrors
          the :meth:`chat_ep`, :meth:`responses_ep`, :meth:`completions_ep`
          and :meth:`embeddings_ep` descriptors).
        """
        return cls._get_impl(api_type).request_path(
            endpoint_url=endpoint_url, provider=provider, stream=stream
        )

    @classmethod
    def chat_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get chat endpoint path.
        """
        return cls._get_impl(api_type).chat_ep()

    @classmethod
    def responses_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get responses endpoint path.
        """
        return cls._get_impl(api_type).responses_ep()

    @classmethod
    def completions_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get completion endpoint path.
        """
        return cls._get_impl(api_type).completions_ep()

    @classmethod
    def embeddings_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get embeddings endpoint path.
        """
        return cls._get_impl(api_type).embeddings_ep()

    @classmethod
    def messages_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get messages endpoint path.
        """
        return cls._get_impl(api_type).messages_ep()

    @classmethod
    def request_headers(cls, api_type: str, provider: Any) -> Dict[str, str]:
        """
        Delegate to the proper implementation to build the outbound
        HTTP headers for ``provider``.
        """
        return cls._get_impl(api_type).request_headers(provider)

    @classmethod
    def request_body(
        cls,
        api_type: str,
        payload: Any,
        provider: Any,
        system_message: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Delegate to the proper implementation to finalise the request
        body for ``provider``.
        """
        return cls._get_impl(api_type).request_body(
            payload, provider, system_message
        )

    @classmethod
    def owns_message_normalization(cls, api_type: str) -> bool:
        """
        Whether the provider type normalises messages by itself.  Unknown
        ``api_type`` values are treated as ``False`` (the router keeps
        its historical normalisation).
        """
        try:
            return bool(cls._get_impl(api_type).owns_message_normalization())
        except ValueError:
            return False

    @classmethod
    def ping_path(cls, api_type: str, provider: Any) -> Optional[str]:
        """
        Provider‑specific health‑check path (``None`` → the monitor falls
        back to its generic probe list).  Unknown ``api_type`` values
        return ``None`` instead of raising.
        """
        try:
            return cls._get_impl(api_type).ping_path(provider)
        except ValueError:
            return None

    @classmethod
    def on_response_status(
        cls, api_type: str, provider: Any, status_code: int
    ) -> None:
        """
        Notify the provider type of the HTTP status of a completed call.

        Purely advisory bookkeeping (e.g. evicting credentials the upstream
        rejected), so a failing hook must never change the response the client
        receives: unknown ``api_type`` values and hook exceptions are swallowed
        and logged, mirroring :meth:`ping_path`.
        """
        try:
            cls._get_impl(api_type).on_response_status(provider, status_code)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug(
                "on_response_status hook failed for api_type %s",
                api_type,
                exc_info=True,
            )

    @classmethod
    def signs_payload(cls, api_type: str) -> bool:
        """
        Whether ``api_type`` authenticates by signing the request body.

        When ``True`` the transport must serialise the payload once, hand those
        exact bytes to :meth:`sign_request` and transmit them as ``data`` —
        re‑serialising after signing breaks the signature.  Unknown
        ``api_type`` values are treated as ``False``.
        """
        try:
            return bool(cls._get_impl(api_type).signs_payload())
        except ValueError:
            return False

    @classmethod
    def sign_request(
        cls,
        api_type: str,
        provider: Any,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes] = None,
    ) -> Dict[str, str]:
        """
        Let ``api_type`` authenticate the assembled request.

        Called with the final URL and the exact body bytes about to be sent,
        which is the only moment a payload signature can be correct.  A failing
        hook must not silently downgrade to an unsigned request — unlike the
        advisory hooks, an exception propagates so the caller surfaces a real
        credential error instead of a confusing ``403`` from the service.
        Unknown ``api_type`` values return ``headers`` unchanged.
        """
        try:
            impl = cls._get_impl(api_type)
        except ValueError:
            return headers
        return impl.sign_request(provider, method, url, headers, body)

    @classmethod
    def signed_body(cls, payload: Any) -> bytes:
        """
        Serialise ``payload`` into the exact bytes a signed request transmits.

        A payload signature is computed over one serialisation, so the same
        bytes must be signed and sent.  Handing ``requests`` a ``json=`` dict
        instead hands it the freedom to re-serialise — different separators, a
        different key order — and the service rejects the request as a signature
        mismatch.  Callers pair this with :meth:`sign_request` and then pass the
        result as ``data=``.

        The encoding is fixed (compact separators, sorted keys, UTF-8): it needs
        only to be *deterministic*, and a stable form also makes the signed body
        diffable in request logs.
        """
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")

    @classmethod
    def tags(
        cls, models_config: Dict[str, Any], merge_to_list: bool = True
    ) -> Dict[str, object] | List:
        """
        Extract *tags* defined in the global model configuration.

        The heavy lifting lives in :meth:`ApiTypesI.tags`; this method simply
        flattens the result when ``merge_to_list`` is ``True``.

        Parameters
        ----------
        models_config : Dict
            Raw configuration dictionary (normally loaded from
            ``models-config.json``) that contains per‑model metadata,
            including a ``"tags"`` entry.
        merge_to_list : bool, optional
            When ``True`` (default) return a flat ``list`` containing **all**
            tags across every API type.  When ``False`` return the original
            mapping ``{api_type: [tags...]}``.

        Returns
        -------
        List or Dict
            * ``list`` – a flattened collection of tags if ``merge_to_list`` is
              ``True``.
            * ``dict`` – the untouched mapping if ``merge_to_list`` is
              ``False``.
        """
        all_tags = ApiTypesI.tags(models_config=models_config)
        if not merge_to_list:
            return all_tags

        res = []
        for models in all_tags.values():
            res.extend(models)
        return res
