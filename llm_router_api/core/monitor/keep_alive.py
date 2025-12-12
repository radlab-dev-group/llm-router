import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass(frozen=True)
class KeepAliveRequest:
    model_name: str
    host: str
    prompt: str


class KeepAlive:
    """
    Encapsulates keep-alive logic: map (model_name, host) -> provider config,
    then send HTTP request to the provider endpoint.
    """

    def __init__(
        self,
        models_configs: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
        prompt: str = "W odpowiedzi wybierz tylko 1 lub 2",
        max_tokens: int = 56,
        temperature: float = 0.0,
    ) -> None:
        self._models_configs = models_configs
        self._logger = logger or logging.getLogger(__name__)
        self._prompt = prompt
        self._max_tokens = max_tokens
        self._temperature = temperature

    def send(self, model_name: str, host: str, prompt: Optional[str] = None) -> None:
        req = KeepAliveRequest(
            model_name=model_name, host=host, prompt=prompt or self._prompt
        )
        provider, api_model_name = self._find_provider(req.model_name, req.host)
        if not provider:
            self._logger.error(
                "KeepAlive: provider not found for model=%s host=%s",
                req.model_name,
                req.host,
            )
            return

        api_type = (provider.get("api_type") or "").lower()
        api_host = (provider.get("api_host") or "").rstrip("/")
        token = provider.get("api_token") or ""

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        payload = {
            "stream": False,
            "model": api_model_name,
            "messages": [{"role": "user", "content": req.prompt}],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }

        endpoint = self._endpoint_for(api_type, api_host)
        if not endpoint:
            self._logger.warning(
                "KeepAlive: unsupported api_type=%s (model=%s)",
                api_type,
                req.model_name,
            )
            return

        try:
            response = requests.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            self._logger.debug(
                "KeepAlive: response model=%s api_type=%s status=%s",
                req.model_name,
                api_type,
                response.status_code,
            )
        except Exception as exc:
            self._logger.error(
                "KeepAlive: request failed model=%s api_type=%s err=%s",
                req.model_name,
                api_type,
                exc,
            )
            self._logger.exception(exc)
            return

        self._logger.info(
            "Sending keep-alive prompt to %s model=%s host=%s",
            api_type,
            req.model_name,
            req.host,
        )

    def _endpoint_for(self, api_type: str, api_host: str) -> Optional[str]:
        if api_type in ("vllm", "openai"):
            return f"{api_host}/v1/chat/completions"
        if api_type == "ollama":
            return f"{api_host}/api/chat"
        return None

    def _find_provider(
        self, model_name: str, host: str
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Returns: (provider_dict, api_model_name)
        """
        normalized_model = (model_name or "").replace("model:", "").strip()

        # models_configs: {model_name: {..., "providers": [...]}}
        for original_model_name, cfg in (self._models_configs or {}).items():
            # match like in current logic: compare normalized names
            normalized_cfg_name = (
                str(original_model_name).replace("model:", "").strip()
            )
            if normalized_cfg_name != normalized_model:
                continue

            for p in cfg.get("providers", []) if isinstance(cfg, dict) else []:
                if p.get("api_host") == host:
                    api_model_name = p.get("model_path") or original_model_name
                    return p, api_model_name

            return None, None

        return None, None
