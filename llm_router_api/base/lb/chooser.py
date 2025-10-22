"""
Provider selection orchestrator.

The :class:`ProviderChooser` class acts as a thin façade around the
different load‑balancing strategies defined in the ``llm_router_api.base.lb``
package.  It allows callers to either supply a concrete strategy instance
or specify a strategy by name (e.g. ``"balanced"``, ``"weighted"``,
``"dynamic_weighted"``, ``"adaptive_base"``).  The chosen strategy is then
used to pick a provider for a given model from a list of candidate
configurations.

Typical usage::

    chooser = ProviderChooser(strategy_name="weighted")
    provider_cfg = chooser.get_provider("gpt-4", provider_list)

If an invalid ``strategy_name`` is supplied, a :class:`RuntimeError` is
raised during initialisation.
"""

from typing import List, Dict, Optional

from llm_router_api.base.lb.strategy import ChooseProviderStrategyI

from llm_router_api.base.lb.balanced import LoadBalancedStrategy
from llm_router_api.base.lb.weighted import WeightedStrategy, DynamicWeightedStrategy

STRATEGIES = {
    "balanced": LoadBalancedStrategy,
    "weighted": WeightedStrategy,
    "dynamic_weighted": DynamicWeightedStrategy,
}


class ProviderChooser:
    """
    Facade for selecting a provider using a configurable load‑balancing strategy.

    Parameters
    ----------
    strategy : ChooseProviderStrategyI, optional
        An explicit strategy instance to use.  If ``None``, the chooser will
        fall back to the ``strategy_name`` argument or, finally, to the
        default :class:`LoadBalancedStrategy`.
    strategy_name : str, optional
        The name of a strategy as defined in the ``STRATEGIES`` mapping.
        This argument is ignored when ``strategy`` is provided.

    Attributes
    ----------
    strategy_name : str | None
        The name of the strategy that was requested (may be ``None``).
    strategy : ChooseProviderStrategyI
        The concrete strategy instance that will be used for provider selection.
    """

    def __init__(
        self,
        strategy: Optional[ChooseProviderStrategyI] = None,
        strategy_name: Optional[str] = None,
    ) -> None:
        """
        Initialize the chooser with either a concrete strategy instance or a
        strategy name.

        The resolution order is:

        1. If ``strategy`` is supplied, it is used directly.
        2. Otherwise, if ``strategy_name`` is provided, the corresponding
           class is looked up in :data:`STRATEGIES` and instantiated.
        3. If neither is supplied, the default :class:`LoadBalancedStrategy`
           is instantiated.

        Raises
        ------
        RuntimeError
            If a ``strategy_name`` is given but does not correspond to any
            known strategy.
        """
        self.strategy_name: Optional[str] = strategy_name
        self.strategy: ChooseProviderStrategyI = strategy or LoadBalancedStrategy()

        if not strategy and self.strategy_name:
            _s = self.__strategy_from_name(strategy_name=self.strategy_name)
            if _s:
                self.strategy = _s

        if not self.strategy:
            raise RuntimeError(f"Strategy {self.strategy_name} not found!")

    def __strategy_from_name(
        self, strategy_name: str
    ) -> Optional[ChooseProviderStrategyI]:
        """
        Resolve a strategy name to an instantiated strategy object.

        The method looks up ``strategy_name`` in the module‑level
        :data:`STRATEGIES` dictionary.  If a matching class is found, it is
        instantiated without arguments and returned; otherwise ``None`` is
        returned.

        Parameters
        ----------
        strategy_name : str
            The key identifying the desired strategy.

        Returns
        -------
        ChooseProviderStrategyI | None
            An instance of the requested strategy, or ``None`` if the name is
            unknown.
        """
        if not self.strategy_name:
            return None
        _cls = STRATEGIES.get(strategy_name)
        return _cls() if _cls else None

    def get_provider(self, model_name: str, providers: List[Dict]) -> Dict:
        """
        Choose a provider for *model_name* from *providers* using the configured strategy.

        The method validates that the ``providers`` list is non‑empty and then
        delegates the actual selection to ``self.strategy.choose``.

        Parameters
        ----------
        model_name : str
            The name of the model for which a provider is required.
        providers : List[Dict]
            A list of provider configuration dictionaries.

        Returns
        -------
        Dict
            The configuration dictionary of the selected provider.

        Raises
        ------
        RuntimeError
            If ``providers`` is empty.
        """
        if not providers:
            raise RuntimeError(f"{model_name} does not have any providers!")
        return self.strategy.choose(model_name, providers)
