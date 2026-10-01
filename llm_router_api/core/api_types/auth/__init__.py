"""
Outbound provider credential helpers for the API types.

One module per cloud/vendor (``google`` today; ``bedrock``, ``azure`` and
friends will follow as more REST providers from the roadmap land) keeps the
token‑signing logic beside the api_type that owns it without cluttering
``api_types`` itself.  Note this is *downstream* authentication towards the
providers — the router's own inbound client auth lives in
:mod:`llm_router_api.core.auth`.
"""
