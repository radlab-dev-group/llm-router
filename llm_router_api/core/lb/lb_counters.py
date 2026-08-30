"""
Shared, worker‑global usage counters for the ``balanced`` / ``weighted``
provider‑selection strategies.

Problem
-------
The historical implementation kept the selection counters in a plain
per‑process dictionary (plus, for ``weighted``, a ``hash()`` salt that varies
with ``PYTHONHASHSEED``).  With a multi‑worker WSGI server (gunicorn with
2+ workers, or multiple containers) each worker only saw its own counters, so
the long‑term distribution did *not* converge to the configured weights and
the "least used" balance was only local.

Solution
--------
Move the counters into **Redis** (the same infrastructure the auth
rate‑limiter already uses) so every worker reads and updates the *same*
counters:

* ``balanced``  – atomic "read all provider counts, increment the minimum".
* ``weighted``  – a single global selection sequence (atomic ``INCR``) drives
  the deterministic CDF walk, so the offset is identical in every worker.

If Redis is not available (client is ``None`` or a command fails) the helper
falls back to an in‑memory counter so routing never breaks.

The counter object is intentionally tiny and has no dependency on any other
strategy class, so it can be shared across strategy instances that represent
different workers of the same service.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LbCounters:
    """
    Worker‑global usage counters backed by Redis (with in‑memory fallback).

    Parameters
    ----------
    redis_client : Optional[Any]
        A Redis client (or a compatible fake) exposing ``hincrby``,
        ``hgetall`` and ``incr``.  When ``None`` (or when a Redis command
        raises) all operations degrade to a process‑local counter.
    key_prefix : str, optional
        Prefix for the Redis keys (default ``"llm-router:lb"``).
    ttl : int, optional
        Optional TTL (seconds) applied to counters so idle models do not
        accumulate forever.  ``0`` (default) means "no expiry".
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        key_prefix: str = "llm-router:lb",
        ttl: int = 0,
        lb_logger: Optional[logging.Logger] = None,
    ) -> None:
        self._redis = redis_client
        self._prefix = key_prefix
        self._ttl = ttl
        self._log = lb_logger or logging.getLogger(__name__)
        # In-memory fallback (used when Redis is absent or errors).
        self._mem: Dict[str, Dict[str, int]] = {}
        self._mem_seq: Dict[str, int] = {}
        self._lock = threading.Lock()

    # -- key helpers --------------------------------------------------------
    def _model_key(self, model_name: str) -> str:
        return f"{self._prefix}:model:{model_name}"

    def _seq_key(self, model_name: str) -> str:
        return f"{self._prefix}:seq:{model_name}"

    def _apply_ttl(self, key: str) -> None:
        if self._ttl and self._redis is not None:
            try:
                self._redis.expire(key, self._ttl)
            except Exception:  # pylint: disable=broad-exception-caught
                # intentional: an optional TTL update must never break routing.
                pass

    # -- balanced: atomic pick-least-and-increment --------------------------
    def pick_least_used(self, model_name: str, keys: List[str]) -> Optional[str]:
        """
        Atomically increment the counter of the *least used* provider and
        return that provider's key.

        If no provider has been used yet the first key is returned (and
        incremented).  Returns ``None`` only when *keys* is empty.
        """
        if not keys:
            return None

        # -- Redis path -----------------------------------------------------
        if self._redis is not None:
            try:
                key = self._model_key(model_name)
                raw = self._redis.hgetall(key) or {}
                # decode bytes -> str (when decode_responses is disabled)
                counts: Dict[str, int] = {}
                for field, val in raw.items():
                    if isinstance(field, bytes):
                        field = field.decode("utf-8")
                    counts[field] = int(val)
                best = None
                best_val = None
                for k in keys:
                    v = counts.get(k, 0)
                    if best is None or v < best_val:
                        best, best_val = k, v
                self._redis.hincrby(key, best, 1)
                self._apply_ttl(key)
                return best
            except Exception as exc:  # noqa: BLE001 - fall back to memory
                # intentional: Redis hiccup must never break routing; the
                # in-memory counter takes over for this call.
                if self._log:
                    self._log.debug(
                        "LbCounters.pick_least_used Redis error (%s); "
                        "using in-memory fallback",
                        exc,
                    )

        # -- in-memory fallback --------------------------------------------
        with self._lock:
            m = self._mem.setdefault(model_name, {})
            # keys is guaranteed non-empty (checked above); seed with the
            # first key so `best` is never None (keeps mypy happy and is
            # equivalent to the previous first-minimum-wins scan).
            best = keys[0]
            best_val = m.get(best, 0)
            for k in keys[1:]:
                v = m.get(k, 0)
                if v < best_val:
                    best, best_val = k, v
            m[best] = best_val + 1
            return best

    # -- weighted: global selection sequence -------------------------------
    def next_sequence(self, model_name: str) -> int:
        """
        Return the next (monotonic) selection index for *model_name*.

        The first call returns ``0``.  When Redis is available this is an
        atomic ``INCR`` so all workers share the same sequence; otherwise an
        in‑memory counter is used.
        """
        if self._redis is not None:
            try:
                key = self._seq_key(model_name)
                val = int(self._redis.incr(key))
                self._apply_ttl(key)
                return val - 1
            except Exception as exc:  # noqa: BLE001 - fall back to memory
                # intentional: same fallback rationale as pick_least_used.
                if self._log:
                    self._log.debug(
                        "LbCounters.next_sequence Redis error (%s); "
                        "using in-memory fallback",
                        exc,
                    )

        with self._lock:
            val = self._mem_seq.get(model_name, -1) + 1
            self._mem_seq[model_name] = val
            return val
