"""
A tiny, dependency‑free retry helper.

This replaces the ``tenacity`` decorator that the original
``llm-router-utils`` apps used. It provides the single function
:func:`with_retries`, which calls a callable up to ``attempts`` times, sleeping
``wait`` seconds between attempts, and:

* returns the first successful result, or
* re‑raises the last exception once all attempts are exhausted.

Network‑level retries are still handled by :class:`llm_router_lib.client.LLMRouterClient`
(it accepts a ``retries`` argument); this helper is used for *application*
level retries, e.g. re‑issuing an LLM call that returned an unusable payload.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional, Tuple, Type

log = logging.getLogger(__name__)

# A single "exception class to retry on" or a tuple of them.
_RETRY_EXC = Tuple[Type[BaseException], ...]


def with_retries(
    fn: Callable[[], Any],
    attempts: int = 5,
    wait: float = 0.0,
    retry_on: _RETRY_EXC = (Exception,),
    name: Optional[str] = None,
) -> Any:
    """
    Call ``fn()`` up to ``attempts`` times, returning the first success.

    Parameters
    ----------
    fn : Callable[[], Any]
        A zero‑argument callable to invoke.
    attempts : int
        Maximum number of attempts. Must be ``>= 1``.
    wait : float
        Seconds to sleep between attempts (``0`` to sleep not at all).
    retry_on : Tuple[Type[BaseException], ...]
        Exception types that trigger a retry. Any other exception propagates
        immediately.
    name : Optional[str]
        Optional label used in log messages.

    Returns
    -------
    Any
        The return value of the first ``fn()`` call that does not raise a
        retriable exception.

    Raises
    ------
    ValueError
        If ``attempts`` is less than ``1``.
    BaseException
        The last exception raised by ``fn()`` once every attempt is spent, or
        any non‑retriable exception immediately.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    label = name if name is not None else "call"
    last_exc: Optional[BaseException] = None

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:  # noqa: PERF203
            last_exc = exc
            if attempt >= attempts:
                log.warning(
                    "%s failed on final attempt %d/%d: %s",
                    label,
                    attempt,
                    attempts,
                    exc,
                )
                break
            log.warning(
                "%s attempt %d/%d failed: %s – retrying",
                label,
                attempt,
                attempts,
                exc,
            )
            if wait:
                time.sleep(wait)

    assert last_exc is not None  # loop always breaks with last_exc set
    raise last_exc
