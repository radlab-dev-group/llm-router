import logging

from abc import ABC
from typing import Optional

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False

from llm_router_api.base.constants import REDIS_PORT, REDIS_HOST
from llm_router_api.base.monitor.provider_monitor import RedisProviderMonitor


class RedisBasedHealthCheckInterface(ABC):
    def __init__(
        self,
        redis_host: str = REDIS_HOST,
        redis_port: int = REDIS_PORT,
        redis_db: int = 0,
        check_interval: float = 30,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        if not REDIS_IS_AVAILABLE:
            raise RuntimeError("Redis is not available. Please install it first.")

        self.redis_client = redis.Redis(
            host=redis_host, port=redis_port, db=redis_db, decode_responses=True
        )

        # Start providers monitor
        self._monitor = RedisProviderMonitor(
            redis_client=self.redis_client,
            check_interval=check_interval,
            clear_buffers=clear_buffers,
            logger=logger,
        )
