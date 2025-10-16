import logging
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from llm_router_lib.exceptions import (
    AuthenticationError,
    RateLimitError,
    LLMRouterError,
)


class HttpRequester:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 10,
        retries: int = 2,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

        self.logger = logger or logging.getLogger(__name__)

        # retry‑policy
        retry_strategy = Retry(
            total=retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _full_url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    def _handle_response(self, resp: requests.Response) -> requests.Response:
        if resp.status_code == 401:
            raise AuthenticationError("Invalid or missing token")
        if resp.status_code == 429:
            raise RateLimitError("Rate limit exceeded")
        if 400 <= resp.status_code < 600:
            raise LLMRouterError(f"HTTP {resp.status_code}: {resp.text}")
        return resp

    def get(self, path: str, **kwargs) -> requests.Response:
        url = self._full_url(path)
        self.logger.debug("GET %s", url)
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        return self._handle_response(resp)

    def post(
        self, path: str, json: Optional[Dict[str, Any]] = None, **kwargs
    ) -> requests.Response:
        url = self._full_url(path)
        self.logger.debug("POST %s | payload=%s", url, json)
        resp = self.session.post(url, json=json, timeout=self.timeout, **kwargs)
        return self._handle_response(resp)
