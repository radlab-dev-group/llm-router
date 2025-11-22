"""
Top‑level definitions for the plugin architecture.

This module defines the abstract :class:`PluginInterface` that all concrete
plugins must inherit from.  The interface standardises how plugins receive a
logger (optional) and how they process incoming payloads via the
:py:meth:`apply` method.
"""

import abc
import logging
from typing import Dict, Optional


class PluginInterface(abc.ABC):
    """
    Abstract base class for all plugins.

    Sub‑classes must provide a concrete implementation of the
    :py:meth:`apply` method.  The ``name`` attribute can be overridden by a
    subclass to give the plugin a human‑readable identifier; it defaults to
    ``None`` when not set.

    Parameters
    ----------
    logger: Optional[logging.Logger]
        An optional logger instance that the plugin can use for structured
        logging.  If ``None`` is supplied, the plugin should either create its
        own logger or operate silently.
    """

    name = None

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialise the plugin base class.

        Stores the supplied ``logger`` for later use by concrete plugin
        implementations.

        Parameters
        ----------
        logger: Optional[logging.Logger]
            A logger instance used for diagnostic output.  It is stored on the
            instance as ``self._logger``.
        """
        self._logger = logger

    @abc.abstractmethod
    def apply(self, payload: Dict) -> Dict:
        """
        Process an input payload and return a transformed payload.

        Concrete plugins must implement this method.  The method receives a
        dictionary representing the input data and must return a dictionary
        with the processed result. Each plugin defines the exact semantics
        of the transformation.

        Parameters
        ----------
        payload: Dict
            The input data to be processed by the plugin.

        Returns
        -------
        Dict
            The processed output data.

        Raises
        ------
        NotImplementedError
            If a subclass does not provide an implementation.
        """
        pass
