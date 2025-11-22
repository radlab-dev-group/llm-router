"""
Executable pipeline for guardrail plugins.

It works the same way as the masker pipeline: an ordered list of plugin
identifiers is supplied, each plugin is registered (if not already), and then
their ``apply`` methods are called sequentially on the payload.
"""

import logging
from typing import Tuple, Dict

from llm_router_plugins.guardrails.plugin_registrator import GuardrailRegistry


class GuardrailPipeline:
    """
    Represents an executable pipeline of guardrail plugins.

    The pipeline is built from an ordered list of plugin identifiers.
    Calling ``apply(payload, *args, **kwargs)`` will invoke each plugin's
    ``apply`` method sequentially, passing the result of one as the input
    to the next.
    """

    def __init__(self, plugin_names: list[str], logger: logging.Logger):
        self._logger = logger

        # Ensure every requested plugin is instantiated and cached.
        for p_name in plugin_names:
            GuardrailRegistry.register(name=p_name, logger=logger)

        # Resolve the concrete plugin instances.
        self._plugin_instances = [
            GuardrailRegistry.get(name) for name in plugin_names
        ]

    def apply(self, payload: Dict) -> Tuple[bool, Dict]:
        """
        Execute the pipeline.

        Args:
            payload: Initial data passed to the first guardrail plugin.
            *args, **kwargs: Additional arguments forwarded to each plugin's
                ``apply`` method.

        Returns:
            True when payload is satisfied, False otherwise.
        """
        for plugin in self._plugin_instances:
            is_safe, message = plugin.apply(payload)
            if not is_safe:
                return False, message
        return True, {}
