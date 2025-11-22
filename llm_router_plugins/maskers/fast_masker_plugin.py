import logging
from typing import Dict, Optional

from llm_router_plugins.plugin_interface import PluginInterface
from llm_router_plugins.maskers.fast_masker.core import FastMasker


class FastMaskerPlugin(PluginInterface):
    name = "fast_masker"

    def __init__(self, logger: Optional[logging.Logger] = None):
        super().__init__(logger=logger)
        self._fast_masker = FastMasker()

    def apply(self, payload: Dict) -> Dict:
        return self._fast_masker.mask_payload_fast(payload=payload)
