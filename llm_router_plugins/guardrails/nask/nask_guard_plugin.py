"""
NASK Guardrail Plugin

This plugin sends the incoming ``payload`` to the NASK guardrail service and
parses the JSON response.  The service URL can be configured through the
environment variable ``LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST_EP``;

The expected response format is:

{
    "results": {
        "detailed": [
            {
                "chunk_index": 0,
                "chunk_text": "...",
                "label": "safe",
                "safe": true,
                "score": 0.9834
            }
        ],
        "safe": true
    }
}

If the request succeeds, ``apply`` returns a dictionary containing the
extracted fields.  If any error occurs (network error, unexpected payload,
missing keys, etc.) the method returns ``{'success': False}``.

---

**Model License:** The model used by this plugin is licensed under **CC BY‑NC‑SA 4.0**.
**Router License:** The LLM router component is licensed under **Apache 2.0**.
Before using the plugin, ensure that your intended use complies with these licenses.

**Authors:** Aleksandra Krasnodębska, Karolina Seweryn, Szymon Łukasik, Wojciech Kusa
(see *PL‑Guard: Benchmarking Language Model Safety for Polish*, 2025).

"""

import json
import logging
from typing import Dict, Optional, Tuple

from llm_router_api.base.constants import GUARDRAIL_NASK_GUARD_HOST_EP
from llm_router_plugins.plugin_interface import HttpPluginInterface


class NASKGuardPlugin(HttpPluginInterface):
    """
    Concrete implementation of :class:`HttpPluginInterface` that
    talks to the NASK guardrail HTTP endpoint.
    """

    name = "nask_guard"

    def __init__(self, logger: Optional[logging.Logger] = None):
        if not len(GUARDRAIL_NASK_GUARD_HOST_EP):
            raise RuntimeError(
                f"When you are using `nask_guard` plugin, you must provide a "
                f"host with model, GUARDRAIL_NASK_GUARD_HOST_EP must be set "
                f"to valid host."
            )

        super().__init__(logger=logger)

    @property
    def base_url(self) -> str:
        """
        Resolve the endpoint URL from the environment variable or fall back to
        the default value.
        """
        return GUARDRAIL_NASK_GUARD_HOST_EP

    def apply(self, payload: Dict) -> Tuple[bool, Dict]:
        """
        Send ``payload`` to the guardrail service, parse the JSON response and
        expose the most relevant fields.

        Parameters
        ----------
        payload: Dict
            The data that should be evaluated by the guardrail.

        Returns
        -------
        Dict
            ``{'success': True, 'safe': <bool>, 'chunk_index': <int>,
            'chunk_text': <str>, 'label': <str>, 'score': <float>}``
            on success, or ``{'success': False}`` on any error.
        """
        try:
            response = self._request(payload)
            results = response.get("results", {})
            safe_overall: bool = bool(results.get("safe", False))

            # detailed = results.get("detailed", [])
            # if not detailed:
            #     # No detailed information – treat as failure
            #     raise ValueError("Missing 'detailed' entries in response")
            # first_chunk = detailed[0]
            # chunk_index: int = first_chunk.get("chunk_index", -1)
            # chunk_text: str = first_chunk.get("chunk_text", "")
            # label: str = first_chunk.get("label", "")
            # safe_chunk: bool = first_chunk.get("safe", False)
            # score: float = first_chunk.get("score", 0.0)
            # Build a concise result dictionary
            return safe_overall, response
        except Exception as exc:
            if self._logger:
                self._logger.error(
                    "NASKGuardPlugin failed to process payload: %s", exc
                )
            return False, {}
