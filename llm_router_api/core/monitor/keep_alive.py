"""
Keep‑alive utility module.

Provides a small wrapper around HTTP calls that periodically ping a model
endpoint to keep the underlying service warm.  The implementation is
unchanged – only documentation strings and comments have been added or
translated to English.
"""

import logging
import requests

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class KeepAliveRequest:
    """
    Simple data holder for a keep‑alive request.
    """

    model_name: str
    host: str
    prompt: str


class KeepAlive:
    """
    Encapsulates keep‑alive logic: map ``(model_name, host)`` → provider
    configuration, then send an HTTP request to the provider endpoint.
    """

    def __init__(
        self,
        models_configs: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
        prompt: str = "Send an empty message.",
        max_tokens: int = 56,
        temperature: float = 0.0,
    ) -> None:
        """
        Initialize the keep‑alive helper.

        Parameters
        ----------
        models_configs: dict
            Mapping of model names to their configuration dictionaries.
        logger: logging.Logger, optional
            Logger instance; if omitted, a module‑level logger is created.
        prompt: str, optional
            Prompt sent to the model – by default a short empty message.
        max_tokens: int, optional
            Maximum number of tokens to request from the model.
        temperature: float, optional
            Sampling temperature for the request.
        """
        self._models_configs = models_configs
        self._logger = logger or logging.getLogger(__name__)
        self._prompt = prompt
        self._max_tokens = max_tokens
        self._temperature = temperature

    def send(self, model_name: str, host: str, prompt: Optional[str] = None) -> None:
        """
        Send a keep‑alive request to the given *host* for *model_name*.

        If the provider cannot be located, an error is logged and the method
        returns silently.

        Parameters
        ----------
        model_name: str
            Name of the model.
        host: str
            Host address (e.g. ``http://localhost:8000``).
        prompt: str, optional
            Prompt to use; falls back to the default if ``None``.
        """
        req = KeepAliveRequest(
            model_name=model_name,
            host=host,
            prompt=prompt or self._prompt,
        )
        provider, api_model_name = self._find_provider(req.model_name, req.host)
        if not provider:
            self._logger.error(
                f"[keep-alive] provider not found "
                f"for model={req.model_name} host={req.host}"
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
                f"[keep-alive] unsupported "
                f"api_type={api_type} (model={req.model_name})"
            )
            return

        try:
            timeout = payload.pop("timeout", 60)
            response = requests.post(
                endpoint, json=payload, headers=headers, timeout=timeout
            )
            response.raise_for_status()
            self._logger.debug(
                f"[keep-alive] response model={req.model_name} "
                f"api_type={req.model_name} status={response.status_code}",
            )
        except Exception as exc:
            self._logger.error(
                "[keep-alive] request failed model=%s api_type=%s err=%s",
                req.model_name,
                api_type,
                exc,
            )
            self._logger.exception(exc)
            return

        self._logger.info(
            f"[keep-alive] Sending prompt to {api_type} "
            f"model={req.model_name} host={req.host}"
        )

    @staticmethod
    def _endpoint_for(api_type: str, api_host: str) -> Optional[str]:
        """
        Resolve the full HTTP endpoint for a given ``api_type``.

        Parameters
        ----------
        api_type: str
            One of ``'vllm'``, ``'openai'``, or ``'ollama'``.
        api_host: str
            Base URL of the provider.

        Returns
        -------
        str | None
            Full endpoint URL or ``None`` if the ``api_type`` is unknown.
        """
        if api_type in ("vllm", "openai"):
            return f"{api_host}/v1/chat/completions"
        if api_type == "ollama":
            return f"{api_host}/api/chat"
        return None

    def _find_provider(
        self, model_name: str, host: str
    ) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Locate the provider configuration for *model_name* on *host*.

        Returns a tuple ``(provider_dict, api_model_name)`` where ``api_model_name``
        is the name used in the provider's API (may differ from the logical model
        name).

        Parameters
        ----------
        model_name: str
            Logical model name requested by the caller.
        host: str
            Host address to match against the provider's ``api_host`` field.

        Returns
        -------
        (dict | None, str | None)
            Provider configuration and the concrete API model name, or ``(None,
            None)`` if no matching provider is found.
        """
        normalized_model = (model_name or "").replace("model:", "").strip()

        # ``models_configs`` structure: {model_name: {..., "providers": [...]}}
        for original_model_name, cfg in (self._models_configs or {}).items():
            normalized_cfg_name = (
                str(original_model_name).replace("model:", "").strip()
            )
            if normalized_cfg_name != normalized_model:
                continue

            # ``cfg`` may be a dict; ensure we iterate over its providers safely
            for p in cfg.get("providers", []) if isinstance(cfg, dict) else []:
                if p.get("api_host") == host:
                    api_model_name = p.get("model_path") or original_model_name
                    return p, api_model_name

            # No matching provider for this model
            return None, None
        return None, None
