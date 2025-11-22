import logging

from llm_router_plugins.maskers.plugin_registrator import MaskerRegistry


class MaskerPipeline:
    """
    Represents an executable pipeline of masker plugins.

    The pipeline is built from an ordered list of plugin identifiers.
    Calling ``apply(payload, *args, **kwargs)`` will invoke each plugin's
    ``apply`` method sequentially, passing the result of one as the input
    to the next.
    """

    def __init__(self, plugin_names: list[str], logger: logging.Logger):
        self._logger = logger

        for p_name in plugin_names:
            MaskerRegistry.register(name=p_name, logger=logger)

        self._plugin_classes = [MaskerRegistry.get(name) for name in plugin_names]

    def apply(self, payload, *args, **kwargs):
        """
        Execute the pipeline.

        Args:
            payload: Initial data passed to the first plugin.
            *args, **kwargs: Additional arguments forwarded to each plugin's ``apply`` method.

        Returns:
            The result produced by the last plugin in the sequence.
        """
        result = payload
        for plugin_instance in self._plugin_classes:
            result = plugin_instance.apply(result, *args, **kwargs)
        return result
