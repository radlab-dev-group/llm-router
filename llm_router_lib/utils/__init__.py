"""Utility helpers for ``llm_router_lib``.

This subpackage currently provides:

* :class:`HttpRequester` — a thin wrapper around ``requests`` that adds logging,
  retries and unified error translation.
* :class:`AsyncHttpRequester` — the ``httpx``‑based asynchronous counterpart of
  :class:`HttpRequester` with the same retry and error‑translation contract.
* :func:`build_payload` — the shared payload‑building contract used by both the
  synchronous and the asynchronous clients.
* :mod:`stream` — normalisation of streaming (SSE) responses into typed
  :class:`~llm_router_lib.data_models.response.StreamEvent` objects.
"""

from llm_router_lib.utils.http import HttpRequester
from llm_router_lib.utils.http_async import AsyncHttpRequester
from llm_router_lib.utils.payload import build_payload
from llm_router_lib.utils.stream import parse_stream_line, iter_events

__all__ = [
    "HttpRequester",
    "AsyncHttpRequester",
    "build_payload",
    "parse_stream_line",
    "iter_events",
]
