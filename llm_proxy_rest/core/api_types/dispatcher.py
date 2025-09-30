from __future__ import annotations

from pydantic import BaseModel
from typing import Dict, List, Type, Any

from llm_proxy_rest.core.api_types.types_i import ApiTypesI

from llm_proxy_rest.core.api_types.vllm import VllmType
from llm_proxy_rest.core.api_types.ollama import OllamaType
from llm_proxy_rest.core.api_types.openai import OpenAIApiType


class ApiTypesDispatcher:
    """
    Dispatcher for API type implementations.

    This class exposes the same methods as `ApiTypesI`, but each method accepts
    a string `api_type` and delegates to the matching concrete implementation.

    Supported `api_type` values (case-insensitive):
    - "ollama"
    - "vllm"
    - "openai"
    """

    _REGISTRY: Dict[str, Type[ApiTypesI]] = {
        "ollama": OllamaType,
        "vllm": VllmType,
        "openai": OpenAIApiType,
    }

    @classmethod
    def _get_impl(cls, api_type: str) -> ApiTypesI:
        """
        Resolve and instantiate the concrete implementation for the given api_type.

        Parameters
        ----------
        api_type : str
            API type identifier.

        Returns
        -------
        _ApiTypes.ApiTypesI
            Concrete implementation instance.

        Raises
        ------
        ValueError
            If the api_type is not supported.
        """
        key = (api_type or "").strip().lower()
        impl = cls._REGISTRY.get(key)
        if impl is None:
            supported = ", ".join(sorted(cls._REGISTRY.keys()))
            raise ValueError(
                f"Unsupported api_type '{api_type}'. Supported: {supported}"
            )
        return impl()

    # Endpoint paths
    @classmethod
    def models_list_ep(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get models list endpoint path.
        """
        return cls._get_impl(api_type).models_list_ep()

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

    # HTTP methods
    @classmethod
    def models_list_method(cls, api_type: str) -> str:
        """
        Delegate to the proper implementation to get models list HTTP method.
        """
        return cls._get_impl(api_type).models_list_method()

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
    def params(cls, api_type: str) -> List[str]:
        """
        Delegate to the proper implementation to get an accepted params list.
        """
        return cls._get_impl(api_type).params()

    @classmethod
    def convert_params(
        cls, api_type: str, model: BaseModel | Dict
    ) -> Dict[str, object]:
        """
        Delegate to the proper implementation
        to convert a high-level model to params.
        """
        return cls._get_impl(api_type).convert_params(model)

    @classmethod
    def tags(
        cls, models_config: Dict[str, Any], merge_to_list: bool = True
    ) -> Dict[str, object] | List:
        all_tags = ApiTypesI.tags(models_config=models_config)
        if not merge_to_list:
            return all_tags

        res = []
        for models in all_tags.values():
            res.extend(models)
        return res
