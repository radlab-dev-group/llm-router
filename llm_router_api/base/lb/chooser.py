from typing import List, Dict, Optional

from llm_router_api.base.lb.strategy import (
    ChooseProviderStrategyI,
    LoadBalancedStrategy,
)


class ProviderChooser:

    def __init__(self, strategy: Optional[ChooseProviderStrategyI] = None) -> None:
        self.strategy: ChooseProviderStrategyI = strategy or LoadBalancedStrategy()

    def get_provider(self, model_name: str, providers: List[Dict]) -> Dict:
        if not providers:
            raise RuntimeError(f"{model_name} does not have any providers!")
        return self.strategy.choose(model_name, providers)
