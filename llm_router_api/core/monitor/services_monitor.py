"""
Keep‑alive monitor module (original) – retained for compatibility.

Runs a background thread that periodically triggers keep‑alive requests for
registered ``(model, host)`` pairs.  The logic is unchanged – only the
docstrings and comments have been translated to English.
"""

import time
import requests
import threading

from typing import Optional

from rdl_ml_utils.utils.logger import prepare_logger

from llm_router_api.base.constants import (
    GUARDRAIL_STRATEGY_PIPELINE_REQUEST,
    GUARDRAIL_WITH_AUDIT_RESPONSE,
    MASKING_STRATEGY_PIPELINE,
    ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS,
    REST_API_LOG_LEVEL,
)
from llm_router_plugins.maskers.registry import MASKERS_HOSTS_DEFINITION
from llm_router_plugins.maskers.fast_masker_plugin import FastMaskerPlugin
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

    EXCLUDE_PLUGINS_TO_CHECK_HOST = [FastMaskerPlugin.name]

    def __init__(
        self,
        check_interval: float = ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        request_timeout: float = 2.0,
    ) -> None:
        """
        Initializes the service monitor with configuration options for periodic checks,
        logging, and request handling.  It also prepares internal strategy pipelines
        and the thread infrastructure used for background execution.

        :param check_interval: Interval, in seconds, between successive service checks.
        :param logger_file_name: Destination file for log output; if ``None`` the
            logger uses the default configuration without a file handler.
        :param logger_level: Logging level for the prepared logger (e.g. ``\"INFO\"``).
        :param request_timeout: Timeout, in seconds, applied to HTTP requests.

        :Attributes:
            check_interval (float): Interval between checks as provided at construction.
            logger (logging.Logger): Logger instance configured via ``prepare_logger``.
            request_timeout (float): Timeout used for outbound HTTP requests.
            available_hosts (dict[str, str]): Mapping of ``strategy_name`` to host that
                responded correctly.

        :Returns:
            None

        """
        self.check_interval = check_interval
        self.logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name,
            log_level=logger_level,
            use_default_config=True,
        )

        self.request_timeout = request_timeout

        self._guard_req_strategies = GUARDRAIL_STRATEGY_PIPELINE_REQUEST or []
        self._guard_resp_strategies = GUARDRAIL_WITH_AUDIT_RESPONSE or []
        self._maskers_strategies = MASKING_STRATEGY_PIPELINE or []
        self._all_strategies = (
            self._guard_req_strategies
            + self._guard_resp_strategies
            + self._maskers_strategies
        )

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
        if ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS <= 0:
            return

        if not len(self._all_strategies):
            self.logger.warning(
                "[services-monitor] There are no strategies to check health "
                "(llm-router-services are not used). "
                "Monitor thread will not be started!"
            )
            return

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
        new_available: dict[str, str] = {}
        for strategy_name in self._all_strategies:
            # Skip excluded plugins
            if strategy_name in self.EXCLUDE_PLUGINS_TO_CHECK_HOST:
                continue

            host = GUARDRAILS_HOSTS_DEFINITION.get(strategy_name)
            if not host:
                host = MASKERS_HOSTS_DEFINITION.get(strategy_name)
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
