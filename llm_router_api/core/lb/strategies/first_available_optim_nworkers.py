"""
First available optimization strategy with per-provider worker slots.

This module provides :class:`FirstAvailableOptimNWorkersStrategy`, a
permissive extension of :class:`FirstAvailableOptimStrategy`.  Instead of
the binary one-consumer lock per provider, every provider exposes
``nworkers`` slots (optional provider configuration field, default ``1``)
so up to ``n`` parallel requests may run on the same provider at the same
time.

Slot counters live in a separate Redis hash ``model:<model_name>:in_use``
(one field per provider, value = number of busy workers; a missing field
means ``0``).  Counters are managed by two locally registered Lua scripts
that keep acquire/release atomic across all router workers.

Selection flow (identical to ``first_available_optim`` steps 1-3, which
become capacity-aware through the overridden acquisition hook):

1. Re-use the last host that served the model (if it has a free slot).
2. Re-use any host that already has the model loaded (free slot).
3. Pick a host that does not yet have the model (free slot).
4. **Least loaded with a free slot** – among all active providers ranked
   by (busy workers, busy/nworkers, config order), atomically acquire the
   first candidate that still has a free slot.

If every provider is saturated the strategy delegates to the plain
first-available loop, which waits until a slot is released and raises
:class:`TimeoutError` after the configured ``timeout``.

Typical usage::

    strategy = FirstAvailableOptimNWorkersStrategy(
        models_config_path='dir/models-config.json'
    )
    provider = strategy.get_provider('model-name', providers_list)
    # ... stream the response ...
    strategy.put_provider('model-name', provider)

"""

import logging

from typing import Any, Dict, List, Optional, Tuple

from llm_router_api.base.constants import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD,
    REDIS_PROTOCOL,
    KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS,
    PROVIDER_MONITOR_INTERVAL_SECONDS,
)
from llm_router_api.core.lb.strategies.first_available_optim import (
    FirstAvailableOptimStrategy,
)
from llm_router_api.core.utils import StrategyHelpers

# Atomically claim one worker slot of a provider *iff* the configured
# limit is not reached yet.  Returns the new counter value on success or
# ``0`` when the provider is already saturated.
_ACQUIRE_SLOT_LUA = """
    local redis_key = KEYS[1]
    local field = ARGV[1]
    local limit = tonumber(ARGV[2]) or 1
    local current = tonumber(redis.call('HGET', redis_key, field)) or 0
    if current < limit then
        redis.call('HSET', redis_key, field, tostring(current + 1))
        return current + 1
    end
    return 0
"""

# Atomically release one worker slot of a provider.  The field is deleted
# once the counter reaches zero; a missing field is treated as ``0`` and
# the call stays a safe no-op (idempotent release).
_RELEASE_SLOT_LUA = """
    local redis_key = KEYS[1]
    local field = ARGV[1]
    local current = tonumber(redis.call('HGET', redis_key, field)) or 0
    if current <= 1 then
        redis.call('HDEL', redis_key, field)
        return 0
    end
    redis.call('HSET', redis_key, field, tostring(current - 1))
    return current - 1
"""


class FirstAvailableOptimNWorkersStrategy(FirstAvailableOptimStrategy):
    """
    Optimized first-available strategy with per-provider worker slots.

    Behaves exactly like :class:`FirstAvailableOptimStrategy` (host-reuse
    steps 1-3, keep-alive bookkeeping, plain first-available fallback) but
    replaces the binary provider lock with a per-provider counter of
    concurrent worker slots (``nworkers`` provider field, default ``1``).
    With ``nworkers=1`` the behaviour is bit-for-bit the classic one.

    Slot state is stored in the Redis hash ``model:<model_name>:in_use``
    (field = provider key, value = busy worker count) and managed
    atomically with locally registered Lua scripts, so multiple
    router workers/instances share the same capacity view.
    """

    def __init__(
        self,
        models_config_path: str,
        redis_host: str = REDIS_HOST,
        redis_password: Optional[str] = REDIS_PASSWORD,
        redis_port: int = REDIS_PORT,
        redis_db: int = REDIS_DB,
        redis_protocol: int = REDIS_PROTOCOL,
        timeout: int = 60,
        monitor_check_interval: float = PROVIDER_MONITOR_INTERVAL_SECONDS,
        clear_buffers: bool = True,
        logger: Optional[logging.Logger] = None,
        ka_monitor_check_interval: float = KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS,
    ) -> None:
        """
        Initialise the nworkers first-available strategy.

        Parameters mirror :class:`FirstAvailableOptimStrategy`; the Redis
        key prefix is namespaced with ``"fa_optim_nworkers_"`` and the
        worker-slot Lua scripts are registered after the base
        initialisation.
        """
        super().__init__(
            models_config_path=models_config_path,
            redis_host=redis_host,
            redis_password=redis_password,
            redis_port=redis_port,
            redis_db=redis_db,
            redis_protocol=redis_protocol,
            timeout=timeout,
            monitor_check_interval=monitor_check_interval,
            clear_buffers=clear_buffers,
            logger=logger,
            ka_monitor_check_interval=ka_monitor_check_interval,
            strategy_prefix="fa_optim_nworkers_",
        )
        # Worker-slot counter scripts (atomic acquire/release).
        self._acquire_slot_script = self.redis_client.register_script(
            _ACQUIRE_SLOT_LUA
        )
        self._release_slot_script = self.redis_client.register_script(
            _RELEASE_SLOT_LUA
        )

    # -----------------------------------------------------------------
    # Key / field helpers for the worker-slot counter
    # -----------------------------------------------------------------
    def _in_use_key(self, model_name: str) -> str:
        """
        Redis hash key holding the busy-worker counters of *model_name*.

        Returns
        -------
        str
            Key in the format ``model:<model_name>:in_use``.
        """
        return f"{self._get_redis_key(model_name)}:in_use"

    def _in_use_field(self, provider: Dict) -> str:
        """
        Redis hash field identifying *provider* inside the ``:in_use`` hash.

        Returns
        -------
        str
            The sanitized provider key (same value ``_provider_key``
            derives); a missing field means ``0`` busy workers.
        """
        return self._provider_key(provider)

    # -----------------------------------------------------------------
    # Overridden acquisition / release (worker slots instead of a lock)
    # -----------------------------------------------------------------
    def _try_acquire(self, model_name: str, provider: Dict) -> Optional[Dict]:
        """
        Atomically claim one worker slot of *provider* for *model_name*.

        The limit is read from the provider's optional ``nworkers`` field
        (see :meth:`StrategyHelpers.nworkers`).  With a limit of ``1`` the
        semantics match the classic binary lock one-to-one.

        On success the provider dictionary is enriched with
        ``__chosen_field`` (the ``:in_use`` hash field) and returned;
        ``None`` is returned when the provider is saturated or the
        acquisition raises.

        Parameters
        ----------
        model_name: str
            The model for which the provider is being acquired.
        provider: dict
            Provider description dictionary.

        Returns
        -------
        Optional[dict]
            The enriched provider dictionary if a slot was acquired,
            otherwise ``None``.
        """
        field = self._in_use_field(provider)
        limit = StrategyHelpers.nworkers(provider)
        try:
            new_count = int(
                self._acquire_slot_script(
                    keys=[self._in_use_key(model_name)], args=[field, limit]
                )
            )
        except Exception:
            # intentional: acquisition errors are non-fatal; the provider
            # is simply skipped and the caller tries the next candidate.
            new_count = 0
        if new_count > 0:
            provider["__chosen_field"] = field
            return provider
        return None

    def put_provider(
        self,
        model_name: str,
        provider: Dict,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Release one worker slot of *provider* (idempotent).

        The counter is decremented atomically by the ``:in_use`` release
        script; the field disappears when the counter reaches zero, and a
        missing field is a safe no-op.  The temporary ``__chosen_field``
        entry is removed from the provider dictionary.

        Parameters
        ----------
        model_name: str
            The model associated with the provider.
        provider: dict
            The provider dictionary returned by :meth:`get_provider`.
        options: Dict[str, Any], optional
            Additional options passed to the strategy.
        """
        field = self._in_use_field(provider)
        try:
            self._release_slot_script(
                keys=[self._in_use_key(model_name)], args=[field]
            )
        except Exception:
            raise  # intentional pass-through of original traceback

        provider.pop("__chosen_field", None)

    # -----------------------------------------------------------------
    # Step 4 – least loaded provider with a free worker slot
    # -----------------------------------------------------------------
    def _optimization_steps(self) -> tuple:
        """
        Optimisation steps of this strategy: the classic steps 1-3 plus
        the load-aware step 4 inserted before the first-available
        fallback.

        Returns
        -------
        tuple
            Bound step methods; each takes ``(model_name, providers)`` and
            returns an acquired provider dictionary or ``None``.
        """
        return (
            self._step1_last_host,
            self._step2_existing_hosts,
            self._step3_unused_host,
            self._step4_least_loaded,
        )

    def _step4_least_loaded(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Pick the least loaded active provider that still has a free slot.

        A single ``HGETALL`` snapshot of the ``:in_use`` hash is taken and
        every active (healthy) provider whose host is free for
        *model_name* is ranked by the key
        ``(busy, busy / nworkers, config index)`` – i.e. the fewest busy
        workers first, then the largest relative free capacity on a tie,
        then the order from the configuration.  Candidates are tried in
        that order with the atomic acquire script; when a candidate loses
        a race (the slot was taken in between) the next candidate is
        tried.

        Parameters
        ----------
        model_name: str
            Model name.
        providers: List[Dict]
            Candidate providers.

        Returns
        -------
        Optional[dict]
            The acquired provider dictionary, or ``None`` when no
            provider has a free slot.
        """
        in_use = self.redis_client.hgetall(self._in_use_key(model_name))
        active_providers = self._get_active_providers(
            model_name=model_name, providers=providers
        )

        ranked: List[Tuple[int, float, int, Dict]] = []
        for index, provider in enumerate(active_providers):
            host = StrategyHelpers.host_from_provider(provider)
            if not host or not self._is_host_free(host, model_name):
                continue
            limit = StrategyHelpers.nworkers(provider)
            busy = int(in_use.get(self._in_use_field(provider), 0) or 0)
            if busy >= limit:
                continue
            ranked.append((busy, busy / limit, index, provider))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        for _, _, _, provider in ranked:
            acquired = self._try_acquire(model_name, provider)
            if acquired:
                return acquired
        return None

    # -----------------------------------------------------------------
    # Buffer cleanup
    # -----------------------------------------------------------------
    def _clear_buffer(self) -> None:
        """
        Remove all Redis keys used by this strategy, including the
        ``:in_use`` worker-slot counters (in addition to the
        optimisation keys cleared by the parent).
        """
        super()._clear_buffer()
        for key in self.redis_client.scan_iter(match="*:in_use"):
            self.logger.debug(f"Removing {self} => {key} from redis")
            self.redis_client.delete(key)
