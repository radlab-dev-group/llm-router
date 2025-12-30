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

from typing import Dict, List, Type, Any

from llm_router_api.core.api_types.types_i import ApiTypesI

from llm_router_api.core.api_types.vllm import VllmType
from llm_router_api.core.api_types.ollama import OllamaType
from llm_router_api.core.api_types.openai import OpenAIApiType

# ----------------------------------------------------------------------------------
# Public constant – the full list of API‑type identifiers recognised by the library.
# ----------------------------------------------------------------------------------
API_TYPES = ["builtin", "openai", "ollama", "lmstudio", "vllm"]


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
        "vllm": VllmType,
        "openai": OpenAIApiType,
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

    def get_proper_endpoint(self, api_type: str, endpoint_url: str) -> str:
        endpoint_url = endpoint_url.strip("/")
        if endpoint_url in ["chat/completions", "api/chat/completions"]:
            return self.chat_ep(api_type=api_type)

        return self.completions_ep(api_type=api_type)

    @classmethod
    def chat_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get chat endpoint path.
        """
        return cls._get_impl(api_type).chat_ep()

    @classmethod
    def completions_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get completion endpoint path.
        """
        return cls._get_impl(api_type).completions_ep()

    @classmethod
    def chat_method(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get chat HTTP method.
        """
        return cls._get_impl(api_type).chat_method()

    @classmethod
    def completions_method(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get completion HTTP method.
        """
        return cls._get_impl(api_type).completions_method()

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
        models_config : dict
            Raw configuration dictionary (normally loaded from
            ``models-config.json``) that contains per‑model metadata,
            including a ``"tags"`` entry.
        merge_to_list : bool, optional
            When ``True`` (default) return a flat ``list`` containing **all**
            tags across every API type.  When ``False`` return the original
            mapping ``{api_type: [tags...]}``.

        Returns
        -------
        list | dict
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
