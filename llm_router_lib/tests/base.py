"""Base test classes for LLM Router integration tests."""

import abc
import json
from typing import TYPE_CHECKING, Any

from llm_router_lib import LLMRouterClient

if TYPE_CHECKING:
    from collections.abc import Callable


class BaseEndpointTest(abc.ABC):
    """Abstract base class for endpoint tests."""

    # Subclasses set these as class attributes; they shadow the None defaults here.
    payload: Any = None
    payload_model: type | None = None

    def __init__(self, client: LLMRouterClient) -> None:
        self._client = client

    @abc.abstractmethod
    def client_method(self) -> "Callable[..., Any]":
        """Return the LLMRouterClient method to invoke for this test."""
        raise NotImplementedError

    def run(self, model_name: str) -> Any:
        """Execute this test against *model_name* and return the result dict."""
        print(f"Running {self.client_method}")
        if self.payload:
            print("- " * 50)
            print(" =========== payload =========== ")
            print(json.dumps(self.payload, indent=2, ensure_ascii=False))

            _p = self.payload.copy()
            _p["model_name"] = model_name
            # Subclasses always set payload_model to a Pydantic model class.
            cls = self.payload_model  # type: ignore[assignment]
            return self.client_method()(payload=cls(**_p))  # pylint: disable=E1102
        return self.client_method()()
