"""
Central registry for guardrail plugins.

It mirrors the structure used for maskers:
* ``MAIN_GUARDRAILS_REGISTRY`` – static mapping from plugin names to their
  factory classes (imported from the concrete plugin modules).
* ``GUARDRAILS_REGISTRY_SESSION`` – mutable mapping that holds instantiated
  plugin objects for the current runtime session.
"""

from llm_router_plugins.guardrails.nask.nask_guard_plugin import NASKGuardPlugin

MAIN_GUARDRAILS_REGISTRY = {
    NASKGuardPlugin.name: NASKGuardPlugin  # **Model is licensed under **CC BY‑NC‑SA 4.0**
}

# Runtime session cache – filled by the registrator.
GUARDRAILS_REGISTRY_SESSION = {}
