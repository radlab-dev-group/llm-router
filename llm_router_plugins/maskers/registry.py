from llm_router_plugins.maskers.fast_masker_plugin import FastMaskerPlugin

MAIN_MASKERS_REGISTRY = {FastMaskerPlugin.name: FastMaskerPlugin}

MASKERS_REGISTRY_SESSION = {}
