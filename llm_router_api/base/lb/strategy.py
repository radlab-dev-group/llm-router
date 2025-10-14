from abc import ABC, abstractmethod
from collections import defaultdict
from typing import List, Dict


class ChooseProviderStrategyI(ABC):

    @staticmethod
    def _provider_key(provider_cfg: Dict) -> str:
        return provider_cfg.get("id") or provider_cfg.get("api_host", "unknown")

    @abstractmethod
    def choose(self, model_name: str, providers: List[Dict]) -> Dict:
        raise NotImplementedError


class LoadBalancedStrategy(ChooseProviderStrategyI):

    def __init__(self) -> None:
        self._usage_counters: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def choose(self, model_name: str, providers: List[Dict]) -> Dict:
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
