from typing import Any, Dict
from abc import ABC, abstractmethod


class GuardrailBase(ABC):
    """Common interface for all guardrail models."""

    @abstractmethod
    def classify_chunks(self, payload: Dict[Any, Any]) -> Dict[str, Any]:
        """Classify the supplied payload and return a result dictionary."""
        pass
