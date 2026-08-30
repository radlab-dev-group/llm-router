"""
Provider selection orchestrator.

The :class:`ProviderChooser` class acts as a thin façade around the
different load‑balancing strategies defined in the ``llm_router_api.core.lb``
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

from typing import Any, Dict, List, Optional

from rdl_ml_utils.utils.logger import prepare_logger

from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.base.constants_base import BalanceStrategies

from llm_router_api.core.lb.strategy_interface import ChooseProviderStrategyI
from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy
from llm_router_api.core.lb.strategies.first_available_optim import (
    FirstAvailableOptimStrategy,
)

from llm_router_api.core.lb.strategies.balanced import LoadBalancedStrategy
from llm_router_api.core.lb.strategies.weighted import (
    WeightedStrategy,
    DynamicWeightedStrategy,
)

STRATEGIES = {
    BalanceStrategies.BALANCED: LoadBalancedStrategy,
    BalanceStrategies.WEIGHTED: WeightedStrategy,
    BalanceStrategies.DYNAMIC_WEIGHTED: DynamicWeightedStrategy,
    BalanceStrategies.FIRST_AVAILABLE: FirstAvailableStrategy,
    BalanceStrategies.FIRST_AVAILABLE_OPTIM: FirstAvailableOptimStrategy,
}


def _build_shared_redis_client() -> Optional[Any]:
    """
    Build a shared Redis client for worker‑global LB counters, or ``None``.

    The client is created **lazily** (no immediate connection) and reuses the
    same Redis endpoint the auth rate‑limiter uses (``LLM_ROUTER_AUTH_REDIS_*``)
    so that all workers/containers observe the *same* selection counters.

    It returns ``None`` (→ in‑memory counters) when:

    * ``redis`` is not installed,
    * no Redis host is configured, or
    * client construction raises for any reason.

    A short socket timeout is set so a downed Redis does not block selection
    for long — :class:`LbCounters` falls back to in‑memory on any error.
    """
    try:
        import redis  # noqa: F401

        from llm_router_api.base.constants import (
            REDIS_HOST,
            REDIS_PORT,
            REDIS_DB,
            REDIS_PASSWORD,
            REDIS_PROTOCOL,
        )
    except Exception:  # redis not installed / constants unavailable
        return None

    if not REDIS_HOST:
        return None

    try:
        return redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            protocol=REDIS_PROTOCOL,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
    except Exception:  # pragma: no cover - defensive
        return None


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
    strategy_name : Optional[str]
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
        redis_client: Optional[Any] = None,
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

        # Optional shared Redis client for worker‑global counters
        # (balanced / weighted).  When ``None`` the strategies fall back to
        # in‑memory counters.
        self._redis_client = redis_client
        if self._redis_client is None:
            # Default to the shared auth Redis endpoint (global across
            # workers) when available; otherwise in‑memory counters.
            self._redis_client = _build_shared_redis_client()
        self.strategy: ChooseProviderStrategyI = strategy or LoadBalancedStrategy(
            models_config_path=models_config_path,
            logger=self._logger,
            redis_client=redis_client,
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

        self._logger.info("[Load balancing] Strategy %s", str(self.strategy))

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
        Optional[ChooseProviderStrategyI]
            An instance of the requested strategy, or ``None`` if the name is
            unknown.
        """
        if not self.strategy_name:
            return None

        _cls = STRATEGIES.get(strategy_name)
        if not _cls:
            raise RuntimeError(f"Strategy {strategy_name} not found!")

        import inspect

        kwargs: Dict[str, Any] = {
            "models_config_path": models_config_path,
            "lb_logger": self._logger,
        }
        # Only the counter‑based strategies (balanced / weighted / dynamic)
        # accept a shared Redis client; pass it when supported.
        try:
            params: Dict[str, Any] = dict(inspect.signature(_cls).parameters)
        except (TypeError, ValueError):  # pragma: no cover
            params = {}
        if "redis_client" in params and self._redis_client is not None:
            kwargs["redis_client"] = self._redis_client
        return _cls(**kwargs)

    def get_provider(
        self, model_name: str, providers: List[Dict], options: Optional[Dict] = None
    ) -> Dict:
        """
        Choose a provider for *model_name* from
        *providers* using the configured strategy.

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
        result = self.strategy.get_provider(
            model_name=model_name, providers=providers, options=options
        )

        # ---- Prometheus: record LB strategy selection (no-op safe) --------
        rm = getattr(self, "_router_metrics", None)
        if rm is not None and hasattr(rm, "record_lb_strategy"):
            try:
                rm.record_lb_strategy(
                    strategy=self.strategy_name or self.strategy.__class__.__name__,
                    model_name=model_name,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                # intentional: metrics must never break provider selection.
                pass

        return result

    def set_router_metrics(self, router_metrics) -> None:
        """
        Inject the RouterMetrics instance (called from engine.py after init).
        This avoids circular import issues at module load time.
        """
        self._router_metrics = router_metrics

    def put_provider(
        self, model_name: str, provider: Dict, options: Optional[Dict] = None
    ) -> None:
        """
        Register or update a provider configuration for a given model.

        This method forwards the call to the currently selected load‑balancing
        strategy’s ``put_provider`` implementation.  It allows the strategy to
        store, cache, or otherwise manage provider metadata (e.g., health
        status, weighting, or custom attributes).  No value is returned; any
        error handling is delegated to the underlying strategy.

        Parameters
        ----------
        model_name : str
            The identifier of the model for which the provider is being added
            or updated (e.g., ``"google/gemma-3-12b-it"``).

        provider : Dict
            A dictionary describing the provider configuration.  The exact
            schema is strategy‑specific but typically includes keys such as
            ``"url"``, ``"api_key"``, ``"weight"``, and optional health‑check
            information.

        options : Dict, optional
            Additional options that are passed straight through to the strategy’s
            ``put_provider`` method.  This can be used for flags like
            ``force_update=True`` or to convey custom metadata.

        Raises
        ------
        RuntimeError
            Propagated from the strategy when the provider cannot be stored,
            for example if the strategy is read‑only or the supplied data is
            malformed.
        """
        self.strategy.put_provider(
            model_name=model_name, provider=provider, options=options
        )
