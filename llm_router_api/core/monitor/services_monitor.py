"""
Keep‑alive monitor module (original) – retained for compatibility.

Runs a background thread that periodically triggers keep‑alive requests for
registered ``(model, host)`` pairs.  The logic is unchanged – only the
docstrings and comments have been translated to English.
"""

import time
import logging
import requests
import threading

from typing import Optional

from llm_router_api.base.constants import (
    GUARDRAIL_STRATEGY_PIPELINE_REQUEST,
    GUARDRAIL_WITH_AUDIT_RESPONSE,
)
from llm_router_plugins.guardrails.registry import GUARDRAILS_HOSTS_DEFINITION


class LLMRouterServicesMonitor:
    """
    Periodically probes the configured guard‑rail hosts and records which
    ones are currently reachable.

    For each strategy name listed in ``GUARDRAIL_STRATEGY_PIPELINE_REQUEST``,
    the monitor checks the associated host (looked‑up via
    ``GUARDRAILS_HOSTS_DEFINITION``) by sending a ``GET`` request to
    ``{host}/api/ping``.  A host is considered *available* when the request
    returns HTTP 200 and a JSON payload ``{"response": "pong"}``.

    The monitor runs in a background thread and updates an internal
    ``available_hosts`` dictionary that callers can query.
    """

    def __init__(
        self,
        check_interval: float = 5.0,
        logger: Optional[logging.Logger] = None,
        request_timeout: float = 2.0,
    ) -> None:
        """
        Parameters
        ----------
        check_interval: float
            Seconds to wait between successive health‑checks.
        logger: logging.Logger, optional
            Logger instance; defaults to a module‑level logger.
        request_timeout: float
            Timeout (seconds) for each ``GET /api/ping`` request.
        """
        self.check_interval = check_interval
        self.logger = logger or logging.getLogger(__name__)
        self.request_timeout = request_timeout

        # Mapping ``strategy_name -> host`` for hosts that responded correctly.
        self.available_hosts: dict[str, str] = {}

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    # --------------------------------------------------------------------- #
    # Public control methods
    # --------------------------------------------------------------------- #
    def start(self) -> None:
        """
        Start the background health‑check thread.
        """
        self._thread.start()
        self.logger.debug("[services-monitor] thread started")

    def stop(self) -> None:
        """
        Stop the background thread and wait for it to finish.
        """
        self._stop_event.set()
        self._thread.join()
        self.logger.debug("[services-monitor] thread stopped")

    # --------------------------------------------------------------------- #
    # Host‑checking helpers
    # --------------------------------------------------------------------- #
    def _probe_host(self, host: str) -> bool:
        """
        Send a ``GET {host}/api/ping`` request and verify the expected payload.

        Returns ``True`` if the host answered with status 200 and the correct JSON,
        otherwise ``False``.
        """
        url = f"{host.rstrip('/')}/api/ping"
        try:
            response = requests.get(url, timeout=self.request_timeout)
            if response.status_code != 200:
                return False
            json_body = response.json()
            return json_body.get("response") == "pong"
        except (
            Exception
        ) as exc:  # noqa: BLE001 – any exception means the host is unavailable
            self.logger.debug(
                "[services-monitor] probe failed for %s: %s", host, exc
            )
            return False

    def _refresh_available_hosts(self) -> None:
        """
        Iterate over all strategy names, check their hosts and update
        ``self.available_hosts`` accordingly.
        """
        req = GUARDRAIL_STRATEGY_PIPELINE_REQUEST or []
        resp = GUARDRAIL_WITH_AUDIT_RESPONSE or []
        new_available: dict[str, str] = {}
        for strategy_name in req + resp:
            host = GUARDRAILS_HOSTS_DEFINITION.get(strategy_name)
            if not host:
                self.logger.warning(
                    "[services-monitor] no host defined for strategy %s",
                    strategy_name,
                )
                continue

            if self._probe_host(host):
                new_available[strategy_name] = host
                self.logger.debug(f"[services-monitor] host {host} is available")
            else:
                self.logger.warning(f"[services-monitor] host {host} is unreachable")

        self.available_hosts = new_available

    def _run(self) -> None:
        """
        Continuously refresh the list of reachable hosts.
        """
        while not self._stop_event.is_set():
            try:
                self._refresh_available_hosts()
            except Exception as exc:  # noqa: BLE001 – keep the thread alive
                self.logger.exception("ServicesMonitor error: %s", exc)

            time.sleep(self.check_interval)
