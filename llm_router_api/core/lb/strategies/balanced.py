import logging

from collections import defaultdict
from typing import List, Dict, Optional, Any

from llm_router_api.core.lb.strategy_interface import ChooseProviderStrategyI


class LoadBalancedStrategy(ChooseProviderStrategyI):

    def __init__(
        self, models_config_path: str, logger: Optional[logging.Logger]
    ) -> None:
        super().__init__(models_config_path=models_config_path, logger=logger)

        self._usage_counters: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        if not providers:
            raise ValueError(f"No providers configured for model '{model_name}'")

        min_used = None
        chosen_cfg = None
        for cfg in providers:
            key = self._provider_key(cfg)
            used = self._usage_counters[model_name][key]

            if min_used is None or used < min_used:
                min_used = used
                chosen_cfg = cfg

        chosen_key = self._provider_key(chosen_cfg)
        self._usage_counters[model_name][chosen_key] += 1

        return chosen_cfg
