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

from rdl_ml_utils.utils.logger import prepare_logger

from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.base.constants_base import BalanceStrategies

from llm_router_api.base.lb.strategy_interface import ChooseProviderStrategyI
from llm_router_api.base.lb.strategies.first_available import RedisBasedStrategy
from llm_router_api.base.lb.strategies.first_available_optim import (
    RedisBasedOptimStrategy,
)

from llm_router_api.base.lb.strategies.balanced import LoadBalancedStrategy
from llm_router_api.base.lb.strategies.weighted import (
    WeightedStrategy,
    DynamicWeightedStrategy,
)

STRATEGIES = {
    BalanceStrategies.BALANCED: LoadBalancedStrategy,
    BalanceStrategies.WEIGHTED: WeightedStrategy,
    BalanceStrategies.DYNAMIC_WEIGHTED: DynamicWeightedStrategy,
    BalanceStrategies.FIRST_AVAILABLE: RedisBasedStrategy,
    BalanceStrategies.FIRST_AVAILABLE_OPTIM: RedisBasedOptimStrategy,
}


class ProviderStrategyFacade:
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
        models_config_path: str,
        strategy: Optional[ChooseProviderStrategyI] = None,
        strategy_name: Optional[str] = None,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
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
        self._logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name,
            log_level=logger_level,
            use_default_config=True,
        )

        self.strategy_name: Optional[str] = strategy_name
        self.strategy: ChooseProviderStrategyI = strategy or LoadBalancedStrategy(
            models_config_path=models_config_path, logger=self._logger
        )

        if not strategy and self.strategy_name:
            _s = self.__strategy_from_name(
                strategy_name=self.strategy_name,
                models_config_path=models_config_path,
            )
            if _s:
                self.strategy = _s

        if not self.strategy:
            raise RuntimeError(f"Strategy {self.strategy_name} not found!")

        self._logger.info(f"[Load balancing] Strategy {self.strategy}")

    def __strategy_from_name(
        self, strategy_name: str, models_config_path: str
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
        if not _cls:
            raise RuntimeError(f"Strategy {strategy_name} not found!")

        return _cls(models_config_path=models_config_path, logger=self._logger)

    def get_provider(
        self, model_name: str, providers: List[Dict], options: Optional[Dict] = None
    ) -> Dict:
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
        options: Optional[Dict], Default is ``None``.
            Additional options to pass to ``self.strategy.choose``.

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
        return self.strategy.get_provider(
            model_name=model_name, providers=providers, options=options
        )

    def put_provider(
        self, model_name: str, provider: Dict, options: Optional[Dict] = None
    ) -> None:
        self.strategy.put_provider(
            model_name=model_name, provider=provider, options=options
        )
