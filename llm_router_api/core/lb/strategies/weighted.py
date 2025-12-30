"""
Weighted provider‑selection strategies.

This module implements two concrete strategies that can be used by the
router to pick a provider for a given model request:

* :class:`WeightedStrategy` – selects a provider according to static
  weights supplied in the provider configuration.  The selection is
  deterministic: a per‑model usage counter is used to generate a
  pseudo‑random offset, ensuring that the long‑term selection frequencies
  converge to the configured weights without relying on the global random
  generator.

* :class:`DynamicWeightedStrategy` – extends :class:`WeightedStrategy` by
  allowing the weights to be changed at runtime and by recording the
  latency (time interval) between successive selections of the same
  provider.  The recorded latencies can be accessed via
  :meth:`DynamicWeightedStrategy.get_latency_history` for further analysis
  or adaptive routing decisions.

Both strategies conform to the
:class:`~llm_router_api.core.lb.strategy.ChooseProviderStrategyI`
interface.
"""

import time
import logging

from collections import deque
from collections import defaultdict
from typing import List, Dict, Optional, Any

from llm_router_api.core.lb.strategy_interface import ChooseProviderStrategyI


class WeightedStrategy(ChooseProviderStrategyI):
    """
    Provider‑selection strategy based on static, normalized weights.

    The strategy interprets the ``weight`` field of each provider
    configuration as a probability weight in the range ``[0, 1]``.  If a
    configuration omits the field, a default weight of ``1.0`` is used.
    Weights less than or equal to zero are treated as ``0`` and the
    corresponding provider will never be selected.

    Selection is performed without external randomness.  A deterministic
    offset derived from a per‑model usage counter is used to traverse the
    cumulative distribution function (CDF) of the normalized weights,
    guaranteeing that over many calls the observed frequencies converge to
    the configured probabilities.

    Attributes
    ----------
    _usage_counters : Dict[str, Dict[str, int]]
        Mapping from model name to a per‑provider usage counter.  The
        inner dictionary maps a provider's unique key to the number of
        times it has been selected for the given model.
    """

    def __init__(
        self, models_config_path: str, logger: Optional[logging.Logger]
    ) -> None:
        """
        Initialize a new :class:`WeightedStrategy` instance.

        The constructor creates an empty usage‑counter dictionary that is
        populated lazily as models are routed.  No external state is
        required.
        """
        super().__init__(models_config_path=models_config_path, logger=logger)

        self._usage_counters: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    @staticmethod
    def _clamp_weight(w: float | str) -> float:
        """
        Clamp a raw weight value to a ``float`` in the interval ``[0, 1]``.

        Parameters
        ----------
        w : float | str
            The raw weight value supplied by the user.  It may be a
            ``float`` or a string representation of a number.

        Returns
        -------
        float
            The clamped weight.  Invalid inputs (e.g. non‑numeric strings)
            are interpreted as ``1.0``.  Values below ``0`` are returned as
            ``0.0`` and values above ``1`` are returned as ``1.0``.
        """
        try:
            w = float(w)
        except (TypeError, ValueError):
            w = 1.0
        if w < 0.0:
            return 0.0
        if w > 1.0:
            return 1.0
        return w

    def _normalized_weights(self, providers: List[Dict]) -> List[float]:
        """
        Compute a list of normalized weights for the supplied providers.

        The method extracts the ``weight`` field from each provider
        configuration, clamps it to the ``[0, 1]`` range and then scales the
        resulting list so that the sum of all weights equals ``1.0``.  If
        the total weight is zero (e.g. all providers have a weight of
        ``0``), the method returns an equal distribution to guarantee that
        a provider can still be chosen.

        Parameters
        ----------
        providers : List[Dict]
            A list of provider configuration dictionaries.

        Returns
        -------
        List[float]
            Normalized weights corresponding to the order of ``providers``.
        """
        weights = []
        for p in providers:
            w = self._clamp_weight(p.get("weight", 1.0))
            weights.append(w)

        total = sum(weights)
        if total <= 0.0:
            # If every weight is zero, fall back to a uniform distribution.
            n = len(providers)
            return [1.0 / n] * n

        return [w / total for w in weights]

    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """
        Select a provider for *model_name* based on static weights.

        The selection algorithm proceeds as follows:

        1. Compute normalized probabilities for the supplied ``providers``.
        2. Build a cumulative distribution function (CDF) from those
           probabilities.
        3. Derive a deterministic pseudo‑random offset ``u`` in the interval
           ``[0, 1)`` using a hash of the model name and the total number of
           selections made for that model so far.
        4. Scan the CDF to find the first index where ``u`` is less than or
           equal to the cumulative probability; the corresponding provider
           is chosen.
        5. Increment the usage counter for the chosen provider.

        Parameters
        ----------
        model_name : str
            Identifier of the model for which a provider is being selected.
        providers : List[Dict]
            List of provider configuration dictionaries.  Each dictionary
            must contain at least the information required by
            :meth:`_provider_key`.
        options: Dict[str, Any], default: None
            Additional options passed to the chosen provider.

        Returns
        -------
        Dict
            The configuration dictionary of the selected provider.

        Raises
        ------
        ValueError
            If ``providers`` is empty.
        """
        if not providers:
            raise ValueError(f"No providers configured for model '{model_name}'")

        probs = self._normalized_weights(providers)

        # Build the cumulative distribution function.
        cdf = []
        acc = 0.0
        for p in probs:
            acc += p
            cdf.append(acc)

        # Deterministic offset based on usage counters.
        total_uses = sum(self._usage_counters[model_name].values()) or 0
        u = (hash((model_name, total_uses)) & 0xFFFFFFFF) / 0x100000000

        # Find the first index where u <= cdf[i].
        idx = 0
        for i, edge in enumerate(cdf):
            if u <= edge:
                idx = i
                break
        chosen_cfg = providers[idx]
        chosen_key = self._provider_key(chosen_cfg)
        self._usage_counters[model_name][chosen_key] += 1
        return chosen_cfg


class DynamicWeightedStrategy(WeightedStrategy):
    """
    Dynamic weighting strategy with latency tracking.

    This subclass augments :class:`WeightedStrategy` by allowing the weight
    associated with a provider to be changed at runtime via
    :meth:`set_weight` or :meth:`set_weight_by_key`.  In addition, the
    strategy records the time interval (latency) between consecutive
    selections of the same provider.  The latency history for each provider
    is stored in a bounded ``deque`` and can be queried with
    :meth:`get_latency_history`.

    The dynamic weights take precedence over the static ``weight`` field
    in the provider configuration.  If a dynamic weight has not been set
    for a particular provider, the static configuration value is used.
    """

    def __init__(
        self,
        models_config_path: str,
        initial_providers: List[Dict] | None = None,
        history_size: int = 10_000,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialise a new :class:`DynamicWeightedStrategy`.

        Parameters
        ----------
        initial_providers : List[Dict] | None, optional
            An optional list of provider configurations that should be
            pre‑loaded with their static weights.  For each provider the
            internal dynamic‑weight mapping is populated using the
            configuration's ``weight`` field (or ``1.0`` if omitted).
        history_size : int, optional
            The maximum number of latency measurements to retain for each
            provider.  The underlying ``deque`` discards the oldest entry
            when the limit is exceeded.  Defaults to ``10_000``.
        """
        super().__init__(models_config_path=models_config_path, logger=logger)

        # Mapping: provider key -> dynamic weight in [0, 1].
        self._dynamic_weights: Dict[str, float] = {}
        self.__init_when_needed(initial_providers=initial_providers)

        # Maximum length of each latency history deque.
        self._history_size = history_size

        # Mapping: provider key -> deque of latency intervals (seconds).
        self._latency_history: Dict[str, deque[float]] = {}

        # Mapping: provider key -> timestamp of the most recent selection.
        self._last_chosen_time: Dict[str, float] = {}

    def __init_when_needed(self, initial_providers: List[Dict] | None) -> None:
        """
        Populate the internal dynamic‑weight table from ``initial_providers``.

        This helper is called during construction.  If ``initial_providers``
        is ``None`` or empty the method does nothing.

        Parameters
        ----------
        initial_providers : List[Dict] | None
            Provider configurations whose static ``weight`` values should be
            copied into the dynamic‑weight mapping.
        """
        if initial_providers:
            for cfg in initial_providers:
                key = self._provider_key(cfg)
                w = cfg.get("weight", 1.0)
                self._dynamic_weights[key] = self._clamp_weight(w)

    def set_weight(self, provider_cfg: Dict, weight: float) -> None:
        """
        Set the dynamic weight for a provider identified by its configuration.

        Parameters
        ----------
        provider_cfg : Dict
            The provider configuration dictionary.  The provider's unique
            key is derived via :meth:`_provider_key`.
        weight : float
            The new weight value.  It will be clamped to the ``[0, 1]`` range.
        """
        key = self._provider_key(provider_cfg)
        self._dynamic_weights[key] = self._clamp_weight(weight)

    def set_weight_by_key(self, provider_key: str, weight: float) -> None:
        """
        Set the dynamic weight for a provider identified directly by its key.

        Parameters
        ----------
        provider_key : str
            The unique identifier of the provider as returned by
            :meth:`_provider_key`.
        weight : float
            The new weight value, clamped to ``[0, 1]``.
        """
        self._dynamic_weights[provider_key] = self._clamp_weight(weight)

    def _normalized_weights(self, providers: List[Dict]) -> List[float]:
        """
        Compute normalized weights using dynamic weights when available.

        For each provider the method first checks whether a dynamic weight
        has been set via :meth:`set_weight` or :meth:`set_weight_by_key`.  If
        present, that value is used; otherwise the static ``weight`` field
        from the provider configuration (default ``1.0``) is used.  The
        resulting list is then normalised so that the sum equals ``1.0``.
        If all weights sum to zero, a uniform distribution is returned.

        Parameters
        ----------
        providers : List[Dict]
            List of provider configuration dictionaries.

        Returns
        -------
        List[float]
            Normalized probabilities corresponding to the order of
            ``providers``.
        """
        weights = []
        for p in providers:
            key = self._provider_key(p)
            if key in self._dynamic_weights:
                w = self._dynamic_weights[key]
            else:
                w = p.get("weight", 1.0)
                w = self._clamp_weight(w)
            weights.append(w)

        total = sum(weights)
        if total <= 0.0:
            # All weights are zero – fall back to uniform distribution.
            n = len(providers)
            return [1.0 / n] * n
        return [w / total for w in weights]

    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """
        Choose a provider using the deterministic weighted algorithm and
        record the latency since the last selection of the same provider.

        The method delegates the actual selection to
        :class:`WeightedStrategy.choose`.  After a provider is chosen, the
        elapsed time since its previous selection (if any) is computed and
        stored in the provider‑specific latency history deque.

        Parameters
        ----------
        model_name : str
            Identifier of the model for which a provider is being selected.
        providers : List[Dict]
            List of provider configuration dictionaries.
        options: Dict[str, Any], default: None
            Additional options passed to the chosen provider.

        Returns
        -------
        Dict
            The configuration dictionary of the selected provider.
        """
        chosen_cfg = super().get_provider(
            model_name=model_name, providers=providers, options=options
        )

        self.__latency_recording(chosen_cfg=chosen_cfg)

        return chosen_cfg

    def __latency_recording(self, chosen_cfg: Dict) -> None:
        """
        Record the time interval (latency) between consecutive selections of
        the same provider.

        The method updates two internal structures:

        * ``_last_chosen_time`` – a mapping from provider key to the timestamp
          of the most recent selection.
        * ``_latency_history`` – a mapping from provider key to a bounded
          ``deque`` that stores the elapsed time (in seconds) between the
          current selection and the previous one.

        If the provider has not been selected before, only the timestamp is
        stored; no latency entry is added.  The size of each deque is limited
        by ``_history_size`` to bound memory usage.

        Parameters
        ----------
        chosen_cfg : Dict
            The configuration dictionary of the provider that has just been
            selected.  The provider's unique key is obtained via
            :meth:`_provider_key`.
        """
        key = self._provider_key(chosen_cfg)
        now = time.time()

        if key in self._last_chosen_time:
            interval = now - self._last_chosen_time[key]
            hist = self._latency_history.setdefault(
                key, deque(maxlen=self._history_size)
            )
            hist.append(interval)
        self._last_chosen_time[key] = now

    def get_latency_history(self, provider_key: str) -> List[float]:
        """
        Retrieve the recorded latency intervals for a given provider.

        Parameters
        ----------
        provider_key : str
            The unique identifier of the provider as returned by
            :meth:`_provider_key`.

        Returns
        -------
        List[float]
            A list of latency measurements (in seconds) ordered from oldest
            to newest.  If no history exists for the provider, an empty list
            is returned.
        """
        return list(self._latency_history.get(provider_key, []))
