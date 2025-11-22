"""
Top‑level definitions for the plugin architecture.

This module defines the abstract :class:`PluginInterface` that all concrete
plugins must inherit from.  The interface standardises how plugins receive a
logger (optional) and how they process incoming payloads via the
:py:meth:`apply` method.
"""

import abc
import logging
from typing import Dict, Optional, Tuple


class PluginInterface(abc.ABC):
    """
    Abstract base class for all plugins.

    Sub‑classes must provide a concrete implementation of the
    :py:meth:`apply` method.  The ``name`` attribute can be overridden by a
    subclass to give the plugin a human‑readable identifier; it defaults to
    ``None`` when not set.
    """

    name = None

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialise the plugin base class.

        Stores the supplied ``logger`` for later use by concrete plugin
        implementations.
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
        """
        pass


class HttpPluginInterface(PluginInterface, abc.ABC):
    """
    Abstract base class for plugins that need to communicate with a remote HTTP
    endpoint.

    Sub‑classes must define the ``base_url`` property that points to the host
    they will query.  The ``_request`` helper performs a POST request with the
    supplied ``payload`` and returns the decoded JSON response.  Any HTTP‑
    related errors are logged (if a logger is available) and re‑raised.

    The concrete ``apply`` method remains abstract – implementations are free
    to post‑process the response as required.
    """

    @property
    @abc.abstractmethod
    def base_url(self) -> str:
        """
        URL of the remote host to which the payload will be sent.
        """
        pass

    @abc.abstractmethod
    def apply(self, payload: Dict) -> Tuple[bool, Dict]:
        """
        Process *payload* using the common HTTP request mechanism.

        Concrete plugins should call ``self._request(payload)`` and then
        transform the returned data as needed.
        """
        pass

    def _request(self, payload: Dict) -> Dict:
        """
        Send *payload* to ``self.base_url`` via an HTTP POST request and return
        the JSON response.
        """
        import requests
        from requests.exceptions import RequestException

        try:
            response = requests.post(self.base_url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except RequestException as exc:
            if self._logger:
                self._logger.error(
                    "HTTP request to %s failed: %s", self.base_url, exc
                )
            raise
