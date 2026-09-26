"""
First available optimization strategy with per-provider worker slots.

This module provides :class:`FirstAvailableOptimNWorkersStrategy`, a
permissive extension of :class:`FirstAvailableOptimStrategy`.  Instead of
the binary one-consumer lock per provider, every provider exposes
``nworkers`` slots (optional provider configuration field, default ``1``)
so up to ``n`` parallel requests may run on the same provider at the same
time.

A slot is a **Redis lease**, not a plain counter: each acquired slot is one
member of a per-(model, provider) sorted set whose score is the moment the
lease expires.  The owning router process renews the leases it holds from
the KeepAliveMonitor thread, so a process that dies mid‑request (OOM kill,
container restart) stops renewing and its slots disappear on their own —
the provider's capacity is recovered without a restart and without a
collective ``DEL`` that would over-admit the still-running requests of the
surviving processes.

Selection flow:

1. Re-use the last host that served the model (if it has a free slot).
2. **Least loaded with a free slot** – among all active providers whose host
   is free for the model, ranked by (busy workers, busy/nworkers, config
   order), atomically acquire the first candidate that still has a free slot.
3. Re-use any host that already has the model loaded (free slot).
4. Pick a host that does not yet have the model (free slot).

Step 2 runs *before* the two host-reuse steps, because those two together
split the provider list on “host already known” / “host not known yet” and
therefore already consider **every** provider with a free slot – keeping
them ahead would always return the first configured provider with capacity
and the load-aware ranking would never decide.  They stay behind it as a
safety net for providers step 2 filters out.

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

import time
import uuid
import logging
import threading

from typing import Any, Dict, List, Optional, Tuple

from llm_router_api.base.constants import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD,
    REDIS_PROTOCOL,
    LB_SLOT_LEASE_SECONDS,
    KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS,
    PROVIDER_MONITOR_INTERVAL_SECONDS,
)
from llm_router_api.core.lb.strategies.first_available_optim import (
    FirstAvailableOptimStrategy,
)
from llm_router_api.core.utils import StrategyHelpers

# Atomically claim one worker slot of a single provider.  Expired leases are
# pruned first, so a slot abandoned by a dead router process is reclaimed
# automatically.  Returns ``1`` when the slot was claimed, ``0`` when the
# provider is already saturated.
#
# KEYS[1] : the per-(model, provider) lease sorted set
# ARGV[1] : the unique lease token
# ARGV[2] : the provider's ``nworkers`` limit
# ARGV[3] : the lease lifetime in milliseconds
# ARGV[4] : "now" in milliseconds, taken from the caller so the whole script
#           is independent of the Redis server clock
_ACQUIRE_SLOT_LUA = """
    local redis_key = KEYS[1]
    local token = ARGV[1]
    local limit = tonumber(ARGV[2]) or 1
    local lease_ms = tonumber(ARGV[3]) or 120000
    local now_ms = tonumber(ARGV[4]) or 0

    redis.call('ZREMRANGEBYSCORE', redis_key, '-inf', now_ms)

    if redis.call('ZCARD', redis_key) < limit then
        redis.call('ZADD', redis_key, now_ms + lease_ms, token)
        redis.call('PEXPIRE', redis_key, lease_ms * 2)
        return 1
    end
    return 0
"""

# Release one worker slot.  Removing the last member makes Redis drop the
# key by itself, and releasing an unknown token is a no-op, so the script is
# idempotent.
#
# KEYS[1] : the per-(model, provider) lease sorted set
# ARGV[1] : the lease token
_RELEASE_SLOT_LUA = """
    local redis_key = KEYS[1]
    local token = ARGV[1]
    return redis.call('ZREM', redis_key, token)
"""

# Key of the provider dictionary entry that carries the lease token from
# :meth:`get_provider` to :meth:`put_provider`.  The token has to survive the
# trip through :class:`~llm_router_api.core.model_handler.ApiModel`, which is
# rebuilt from ``as_dict()`` on release.
LEASE_FIELD = "__lease"


class FirstAvailableOptimNWorkersStrategy(FirstAvailableOptimStrategy):
    """
    Optimized first-available strategy with per-provider worker slots.

    Behaves like :class:`FirstAvailableOptimStrategy` (host-reuse, keep-alive
    bookkeeping, plain first-available fallback) but replaces the binary
    provider lock with a per-provider set of concurrent worker slots
    (``nworkers`` provider field, default ``1``) and ranks by load *before*
    the host-reuse steps, so a saturated hot host spreads to the least loaded
    provider instead of to the next one in configuration order.

    With ``nworkers=1`` a provider still admits exactly one request at a time,
    but the state lives in this strategy's own key namespace, so it is not
    shared with ``first_available`` / ``first_available_optim`` running
    against the same Redis database.
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
        slot_lease_seconds: int = LB_SLOT_LEASE_SECONDS,
    ) -> None:
        """
        Initialise the nworkers first-available strategy.

        Parameters mirror :class:`FirstAvailableOptimStrategy`; the Redis
        keys of this strategy are namespaced with ``"fa_optim_nworkers_"``
        and the worker-slot scripts are registered after the base
        initialisation.

        slot_lease_seconds: int, optional
            Lifetime of a single held worker slot.  It is renewed for as long
            as this process keeps the request, so it only has to exceed the
            interval between two KeepAliveMonitor ticks by a safe margin to
            keep live slots, while bounding how long a crashed process
            occupies a provider.
        """
        self.slot_lease_seconds = slot_lease_seconds

        # Leases held by *this* process: token -> (model_name, lease key).
        # Guarded because a router serves requests from many threads.
        self._held_leases: Dict[str, Tuple[str, str]] = {}
        self._leases_lock = threading.Lock()
        # monotonic deadline of the next renewal batch (see _renew_held_leases)
        self._next_renew_at = 0.0

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
            on_tick_callback=self._renew_held_leases,
        )
        # Worker-slot counter scripts (atomic acquire/release).
        self._acquire_slot_script = self.redis_client.register_script(
            _ACQUIRE_SLOT_LUA
        )
        self._release_slot_script = self.redis_client.register_script(
            _RELEASE_SLOT_LUA
        )

    # -----------------------------------------------------------------
    # Key namespace
    # -----------------------------------------------------------------
    def _get_redis_key(self, model_name: str) -> str:
        """
        Return the model key namespaced by :attr:`strategy_prefix`.

        ``RedisBasedStrategy._get_redis_key`` ignores the prefix, which makes
        every first-available flavour share ``model:<model>``,
        ``model:<model>:last_host`` and ``model:<model>:hosts``.  Overriding
        it here keeps the whole model key family of this strategy inside its
        own namespace without changing the key names of the two parent
        strategies for existing deployments.

        Host occupancy (``host:<host>``) deliberately stays unprefixed: which
        model occupies a physical host is a property of the host, not of the
        strategy looking it up.
        """
        prefix = getattr(self, "strategy_prefix", "") or ""
        return f"{prefix}{super()._get_redis_key(model_name)}"

    # -----------------------------------------------------------------
    # Key / field helpers for the worker-slot leases
    # -----------------------------------------------------------------
    def _in_use_key(self, model_name: str, provider: Dict) -> str:
        """
        Redis sorted-set key holding the live worker-slot leases of *provider*.

        Returns
        -------
        str
            Key in the format ``<prefix>model:<model_name>:in_use:<provider_key>``.

        Notes
        -----
        One key per (model, provider) rather than one per model, so
        ``ZCARD`` is the provider's busy count directly and an empty set is
        dropped by Redis without any cleanup of ours.
        """
        return f"{self._get_redis_key(model_name)}:in_use:{self._provider_key(provider)}"

    def _busy_count(self, model_name: str, provider: Dict) -> int:
        """
        Number of live (not yet expired) slots currently held on *provider*.
        """
        return self._busy_counts(model_name, [provider]).get(
            self._provider_key(provider), 0
        )

    def _busy_counts(self, model_name: str, providers: List[Dict]) -> Dict[str, int]:
        """
        Live slot count per provider, fetched in a single round trip.

        A lease is live when its expiry score is still in the future, so
        expired members are excluded by the ``ZCOUNT`` itself and no pruning
        round trip is needed.  A Redis failure degrades to “nothing busy”
        rather than breaking selection: the atomic acquire script does the
        real admission control and it prunes before counting.

        Returns
        -------
        Dict[str, int]
            Mapping of provider key to busy slot count; providers whose count
            could not be read are reported as ``0``.
        """
        counts: Dict[str, int] = {self._provider_key(p): 0 for p in providers}
        if not providers:
            return counts

        now_ms = self._now_ms()
        try:
            pipe = self.redis_client.pipeline(transaction=False)
            for provider in providers:
                pipe.zcount(
                    self._in_use_key(model_name, provider),
                    f"({now_ms}",
                    "+inf",
                )
            results = pipe.execute()
        except Exception as exc:
            self.logger.warning(
                "%s: could not read worker-slot counts for model '%s': %s",
                self,
                model_name,
                exc,
            )
            return counts

        for provider, count in zip(providers, results):
            if isinstance(count, Exception):
                continue
            counts[self._provider_key(provider)] = int(count)
        return counts

    @staticmethod
    def _now_ms() -> int:
        """
        Current wall-clock time in milliseconds (lease time base).
        """
        return int(time.time() * 1000)

    # -----------------------------------------------------------------
    # Overridden acquisition / release (worker slots instead of a lock)
    # -----------------------------------------------------------------
    def _try_acquire(self, model_name: str, provider: Dict) -> Optional[Dict]:
        """
        Atomically claim one worker slot of *provider* for *model_name*.

        The limit is read from the provider's optional ``nworkers`` field
        (see :meth:`StrategyHelpers.nworkers`).  With a limit of ``1`` the
        provider admits exactly one request at a time.

        A **copy** of *provider* is annotated with the lease token and
        returned; the dictionary handed in is never mutated.  That matters
        more here than for the binary lock: ``nworkers > 1`` lets several
        threads acquire the same provider concurrently, and they all get the
        same shared configuration dictionary, so writing the token into it
        would let one request release another request's slot.

        Parameters
        ----------
        model_name: str
            The model for which the provider is being acquired.
        provider: dict
            Provider description dictionary.

        Returns
        -------
        Optional[dict]
            The copied provider dictionary carrying
            :data:`LEASE_FIELD`, or ``None`` when the provider is saturated
            or the acquisition raises.
        """
        acquired = dict(provider)
        token = uuid.uuid4().hex
        lease_ms = int(self.slot_lease_seconds) * 1000
        limit = StrategyHelpers.nworkers(acquired)
        lease_key = self._in_use_key(model_name, acquired)
        try:
            ok = int(
                self._acquire_slot_script(
                    keys=[lease_key],
                    args=[token, limit, lease_ms, self._now_ms()],
                )
            )
        except Exception as exc:
            # Acquisition errors are non-fatal: the provider is skipped and
            # the caller tries the next candidate.  Logged, because a Redis
            # outage surfaces here and nowhere else (the caller then spins
            # until the documented TimeoutError).
            self.logger.warning(
                "%s: could not acquire a slot of provider %r for model '%s': %s",
                self,
                self._provider_key(acquired),
                model_name,
                exc,
            )
            return None

        if ok != 1:
            return None

        acquired[LEASE_FIELD] = token
        with self._leases_lock:
            self._held_leases[token] = (model_name, lease_key)
        return acquired

    def put_provider(
        self,
        model_name: str,
        provider: Dict,
        options: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Release the worker slot held for *provider* (idempotent).

        The slot is identified by the lease token stored under
        :data:`LEASE_FIELD`, so a release without a token cannot guess which
        request it belongs to and does nothing — the lease expires on its
        own.  A failing release is logged rather than raised: the caller is
        already on its way out of the request and the lease bounds the damage.

        Parameters
        ----------
        model_name: str
            The model associated with the provider.
        provider: dict
            The provider dictionary returned by :meth:`get_provider`.
        options: Dict[str, Any], optional
            Additional options passed to the strategy.
        """
        token = provider.get(LEASE_FIELD)
        provider.pop(LEASE_FIELD, None)
        provider.pop("__chosen_field", None)

        if not token:
            self.logger.debug(
                "%s: no lease token for provider %r (model '%s'), "
                "nothing to release",
                self,
                self._provider_key(provider),
                model_name,
            )
            return

        with self._leases_lock:
            held = self._held_leases.pop(token, None)
        lease_key = held[1] if held else self._in_use_key(model_name, provider)

        try:
            self._release_slot_script(keys=[lease_key], args=[token])
        except Exception as exc:
            self.logger.warning(
                "%s: could not release the slot of provider %r "
                "(model '%s'); it expires in %ds: %s",
                self,
                self._provider_key(provider),
                model_name,
                self.slot_lease_seconds,
                exc,
            )

    def _renew_held_leases(self) -> None:
        """
        Push the expiry of every slot this process holds into the future.

        Invoked from the KeepAliveMonitor thread on every tick (see
        ``on_tick_callback``).  A process that dies stops renewing, so its
        leases lapse and the providers' capacity comes back by itself.

        The monitor ticks far more often than a lease needs (once a second by
        default against a 120 s lease), so the writes are throttled to every
        third of the lease lifetime.  A slot acquired right after a batch
        still carries its full lifetime, so the next batch finds it with two
        thirds of that margin left.
        """
        with self._leases_lock:
            held = dict(self._held_leases)
        if not held:
            return

        now = time.monotonic()
        if now < self._next_renew_at:
            return
        self._next_renew_at = now + max(1.0, self.slot_lease_seconds / 3.0)

        score = self._now_ms() + int(self.slot_lease_seconds) * 1000
        try:
            pipe = self.redis_client.pipeline(transaction=False)
            for token, (_model_name, lease_key) in held.items():
                pipe.zadd(lease_key, {token: score})
                pipe.pexpire(lease_key, int(self.slot_lease_seconds) * 2000)
            pipe.execute()
        except Exception as exc:
            # Transient failure: the next batch renews, and until then the
            # leases still have two thirds of their lifetime left.
            self.logger.warning(
                "%s: could not renew %d worker slot(s): %s",
                self,
                len(held),
                exc,
            )

    # -----------------------------------------------------------------
    # Step 2 – least loaded provider with a free worker slot
    # -----------------------------------------------------------------
    def _optimization_steps(self) -> tuple:
        """
        Optimisation steps of this strategy.

        The load-aware step runs directly after “reuse the last host” and
        **before** the two host-reuse steps of the parent: those two split
        ``providers`` on “host already known” / “host not known yet”, so
        together they consider every provider that has a free slot and would
        always answer with the first one in configuration order.  Steps 3 and
        4 are kept behind it as a safety net for providers the load-aware step
        does not rank.

        Returns
        -------
        tuple
            Bound step methods; each takes ``(model_name, providers)`` and
            returns an acquired provider dictionary or ``None``.
        """
        return (
            self._step1_last_host,
            self._step4_least_loaded,
            self._step2_existing_hosts,
            self._step3_unused_host,
        )

    def _step4_least_loaded(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Pick the least loaded active provider that still has a free slot.

        Every active (healthy) provider whose host is free for *model_name* is
        ranked by ``(busy, busy / nworkers, config index)`` – the fewest busy
        workers first, then the largest relative free capacity on a tie, then
        the order from the configuration.  Candidates are tried in that order
        with the atomic acquire script; when a candidate loses a race (the
        slot was taken in between) the next candidate is tried.

        The config index comes from the *caller's* ``providers`` list, not from
        the position in :meth:`_get_active_providers` – that list is rebuilt
        from a Redis ``SMEMBERS`` set, whose iteration order has nothing to do
        with the configuration file.

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
        active_providers = self._get_active_providers(
            model_name=model_name, providers=providers
        )
        if not active_providers:
            return None

        config_order = {self._provider_key(p): i for i, p in enumerate(providers)}
        busy = self._busy_counts(model_name, active_providers)

        ranked: List[Tuple[int, float, int, Dict]] = []
        for provider in active_providers:
            host = StrategyHelpers.host_from_provider(provider)
            if not host or not self._is_host_free(host, model_name):
                continue
            limit = StrategyHelpers.nworkers(provider)
            held = busy.get(self._provider_key(provider), 0)
            if held >= limit:
                continue
            ranked.append(
                (
                    held,
                    held / limit,
                    config_order.get(
                        self._provider_key(provider), len(config_order)
                    ),
                    provider,
                )
            )

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
        Remove this strategy's optimisation keys from Redis.

        Two deliberate departures from the parent implementation:

        * the scan is restricted to :attr:`strategy_prefix`, so starting one
          router does not wipe the state of a different strategy sharing the
          same Redis database;
        * the ``:in_use`` worker-slot leases are **never** cleared.  They
          describe slots held by other, still-running processes of the same
          router, and deleting them lets those providers be over-admitted
          until the counters drift back.  Recovery from a crashed process is
          the job of the lease expiry, not of a start-time flush.
        """
        prefix = getattr(self, "strategy_prefix", "") or ""
        for suffix in (":last_host", ":hosts", ":occupancy"):
            for key in self.redis_client.scan_iter(match=f"{prefix}*{suffix}"):
                self.logger.debug(f"Removing {self} => {key} from redis")
                self.redis_client.delete(key)
