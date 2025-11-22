"""
Helper that registers guardrail plugins on demand, similar to the masker
registrator.

Usage:
    GuardrailRegistry.register(name="name", logger=my_logger)
    plugin = GuardrailRegistry.get("name")
"""

import logging
from typing import Optional

from llm_router_plugins.guardrails.registry import (
    MAIN_GUARDRAILS_REGISTRY,
    GUARDRAILS_REGISTRY_SESSION,
)


class GuardrailRegistry:
    """Central registry for guardrail plugins."""

    @staticmethod
    def register(name: str, logger: Optional[logging.Logger] = None) -> None:
        """
        Register a guardrail plugin for the current session.

        Args:
            name: Identifier of the guardrail plugin (must exist in
                  ``MAIN_GUARDRAILS_REGISTRY``).
            logger: Optional logger that will be passed to the plugin's
                    constructor.
        """
        if name not in MAIN_GUARDRAILS_REGISTRY:
            raise KeyError(
                f"Guardrail '{name}' not found in registry: {MAIN_GUARDRAILS_REGISTRY}"
            )

        # Already registered – nothing to do.
        if name in GUARDRAILS_REGISTRY_SESSION:
            return

        # Instantiate the plugin and store it in the session cache.
        _cls = MAIN_GUARDRAILS_REGISTRY[name](logger=logger)
        GUARDRAILS_REGISTRY_SESSION[name] = _cls

        if logger:
            logger.info(
                f"[guardrail] Registering guardrail '{name}' for plugin '{_cls}'"
            )

    @staticmethod
    def get(name: str):
        """
        Retrieve a registered guardrail plugin instance by name.

        Raises:
            KeyError: If the plugin has not been registered yet.
        """
        try:
            return GUARDRAILS_REGISTRY_SESSION[name]
        except KeyError as exc:
            raise KeyError(
                f"Guardrail '{name}' not found in registry. "
                f"Available plugins: {list(GUARDRAILS_REGISTRY_SESSION.keys())}"
            ) from exc

    @staticmethod
    def list_plugins() -> list[str]:
        """Return the list of guardrail names currently registered in the session."""
        return list(GUARDRAILS_REGISTRY_SESSION.keys())
