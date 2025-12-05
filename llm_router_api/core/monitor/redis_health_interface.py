"""
Redis‑based health‑check interface.

This module provides an abstract base class that establishes a connection
to a Redis server and starts a
:class:`~llm_router_api.core.monitor.provider_monitor.RedisProviderMonitor`.
Concrete strategy implementations inherit from this class to obtain a
ready‑to‑use ``redis_client`` and a health‑monitoring ``_monitor`` instance,
without having to repeat the connection boiler‑plate.
"""

import logging

from abc import ABC
from typing import Optional

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from llm_router_api.base.constants import (
    REDIS_PORT,
    REDIS_HOST,
    REDIS_DB,
    REDIS_PASSWORD,
)
from llm_router_api.core.monitor.provider_monitor import RedisProviderMonitor


class RedisBasedHealthCheckInterface(ABC):
    """
    Abstract mix‑in that equips a subclass with Redis connectivity and provider
    health monitoring.

    Sub‑classes typically combine this mix‑in with a load‑balancing strategy
    (e.g., a provider‑selection interface).  The mix‑in handles:

    * Validation that the ``redis`` package is installed.
    * Creation of a :class:`redis.Redis` client using configurable connection
      parameters.
    * Instantiation of :class:`~llm_router_api.core.monitor.provider_monitor.RedisProviderMonitor`,
      which periodically checks provider health and can optionally clear
      stale state.

    The resulting ``self.redis_client`` and ``self._monitor`` attributes are
    ready for use by the concrete implementation.
    """

    def __init__(
        self,
        redis_host: str = REDIS_HOST,
        redis_port: int = REDIS_PORT,
        redis_password: str = REDIS_PASSWORD,
        redis_db: int = REDIS_DB,
        check_interval: float = 30,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialise the Redis connection and the health‑monitor.

        Parameters
        ----------
        redis_host : str, optional
            Hostname or IP address of the Redis server.  Defaults to the value
            defined in :data:`llm_router_api.base.constants.REDIS_HOST`.
        redis_port : int, optional
            TCP port on which Redis is listening.  Defaults to
            :data:`llm_router_api.base.constants.REDIS_PORT`.
        redis_password : str, optional
            Password for authenticated Redis connections.  Defaults to
            :data:`llm_router_api.base.constants.REDIS_PASSWORD`.
        redis_db : int, optional
            Database index to use.  Defaults to
            :data:`llm_router_api.base.constants.REDIS_DB`.
        check_interval : float, optional
            Interval, in seconds, between health‑check cycles performed by the
            :class:`RedisProviderMonitor`.  A value of ``30`` seconds is used by
            default.
        clear_buffers : bool, optional
            If ``True`` the monitor clears any stale state before starting its
            first check.  Defaults to ``True``.
        logger : logging.Logger | None, optional
            Optional logger instance for the monitor to emit diagnostic messages.
            If omitted, the monitor creates a default logger.

        Raises
        ------
        RuntimeError
            If the ``redis`` package cannot be imported, indicating that Redis
            support is not available in the current environment.
        """

        if not REDIS_IS_AVAILABLE:
            raise RuntimeError("Redis is not available. Please install it first.")

        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
            password=redis_password,
        )

        # Start providers monitor
        self._monitor = RedisProviderMonitor(
            redis_client=self.redis_client,
            check_interval=check_interval,
            clear_buffers=clear_buffers,
            logger=logger,
        )
