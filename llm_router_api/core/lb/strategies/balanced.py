import logging

from typing import Any, List, Dict, Optional

from llm_router_api.core.lb.lb_counters import LbCounters
from llm_router_api.core.lb.strategy_interface import ChooseProviderStrategyI


class LoadBalancedStrategy(ChooseProviderStrategyI):
    """
    Least‑used provider selection.

    The per‑provider usage counters are stored in a shared, worker‑global
    :class:`~llm_router_api.core.lb.lb_counters.LbCounters` (Redis‑backed when
    a ``redis_client`` is supplied, in‑memory otherwise) so that multiple
    workers/containers all observe and update the *same* counters.
    """

    def __init__(
        self,
        models_config_path: str,
        logger: Optional[logging.Logger] = None,
        redis_client: Optional[Any] = None,
        key_prefix: str = "llm-router:lb",
        ttl: int = 0,
    ) -> None:
        super().__init__(models_config_path=models_config_path, logger=logger)
        self._counters = LbCounters(
            redis_client=redis_client,
            key_prefix=key_prefix,
            ttl=ttl,
            lb_logger=logger,
        )

    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict]:
        if not providers:
            raise ValueError(f"No providers configured for model '{model_name}'")

        keys = [self._provider_key(cfg) for cfg in providers]

        # Atomic "pick the least used and increment it" (Redis or memory).
        chosen_key = self._counters.pick_least_used(model_name, keys)
        for cfg in providers:
            if self._provider_key(cfg) == chosen_key:
                return cfg
        return providers[0]
