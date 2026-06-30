"""
CLI commands for generating a models-config.json from auto-discovered local providers.

Usage::

    llm-router config discover localhost --config-file generated-config.json
    llm-router config discover localhost 192.168.1.50 10.0.0.1
"""

from __future__ import annotations

import sys
import json
import argparse
import requests

from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Host parsing
# ---------------------------------------------------------------------------


def _parse_host(raw: str) -> Tuple[str, int]:
    """Split ``host:port`` into ``(host, port)``.

    If no explicit port is given (no colon in *raw*), returns ``(raw, 0)`` —
    the caller then uses the provider's default ports.

    Examples
    --------
    >>> _parse_host("localhost")
    ('localhost', 0)
    >>> _parse_host("192.168.100.65:8080")
    ('192.168.100.65', 8080)
    >>> _parse_host("::1")
    ('::1', 0)
    """
    # Strip ``http://`` / ``https://`` prefix if present.
    scheme_end = raw.find("://")
    if scheme_end != -1:
        raw = raw[scheme_end + 3 :]

    # Bracket-notation IPv6: [::1]:8080
    if raw.startswith("["):
        end = raw.find("]")
        if end != -1 and ":" in raw[end + 1 :]:
            host_port = raw[end + 1 :]
            port_str = host_port.lstrip(":")
            return raw[1:end], int(port_str)
        return raw, 0
    # Plain IPv4 or hostname:port (at most one colon).
    if raw.count(":") <= 1:
        parts = raw.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            return parts[0], int(parts[1])
        return raw, 0
    # Two or more colons → bare IPv6 address (e.g. ``::1``, ``fe80::``).
    return raw, 0


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDER_DEFS: List[Dict[str, Any]] = [
    {
        "api_type": "ollama",
        "group_name": "ollama_models",
        "ports": [11434, 18765],
        "health_path": "/",
        "models_path": "/api/tags",
        # Response: {"models": [{"name": "..."}, ...]}
        "model_name_key": "id",  # we normalise to {"id": name} before lookup
        "tool_calling_hint": False,
    },
    {
        "api_type": "vllm",
        "group_name": "vllm_models",
        "ports": [8000, 7000],
        "health_path": "/health",
        "models_path": "/v1/models",
        # Response: {"data": [{"id": "...", "root": "..."}, ...]} (OpenAI format)
        "model_name_key": "id",
        "tool_calling_hint": True,
    },
    {
        "api_type": "lmstudio",
        "group_name": "lmstudio_models",
        "ports": [1234, 1235],
        "health_path": "/",
        "models_path": "/v1/models",
        # Response: {"data": [{"id": "..."}, ...]} (OpenAI format)
        "model_name_key": "id",
        "tool_calling_hint": True,
    },
]


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _health_check(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return ``True`` when a HTTP service responds on ``{host}:{port}``."""
    try:
        resp = requests.get(f"http://{host}:{port}/", timeout=timeout)
        return resp.status_code < 500
    except (requests.RequestException, OSError):
        return False


def _health_check_with_path(
    host: str, port: int, path: str, timeout: float = 0.5
) -> bool:
    """Return ``True`` when a HTTP service responds on ``{host}:{port}{path}``."""
    try:
        resp = requests.get(f"http://{host}:{port}{path}", timeout=timeout)
        return resp.status_code < 500
    except (requests.RequestException, OSError):
        return False


def _fetch_ollama_models(host: str, port: int) -> List[Dict[str, Any]]:
    """Fetch Ollama model info via ``GET /api/tags``.

    Returns a list of dicts with at least ``id`` and optional metadata
    (context_length, capabilities, etc.).
    """
    url = f"http://{host}:{port}/api/tags"
    try:
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        models: List[Dict[str, Any]] = []
        for m in data.get("models", []):
            detail = m.get("details", {})
            # Ollama puts capabilities both at top-level and under details.
            top_caps = set(m.get("capabilities") or [])
            det_caps = set(detail.get("capabilities") or []) | set(
                detail.get("families") or []
            )
            all_caps = top_caps | det_caps
            models.append(
                {
                    "id": m["name"],
                    "context_length": detail.get("context_length"),
                    "tool_calling": any(
                        kw in all_caps
                        for kw in ("tools", "tool_use", "function_call")
                    ),
                }
            )
        return models
    except (requests.RequestException, OSError, KeyError, ValueError):
        return []


def _fetch_openai_style_models(host: str, port: int) -> List[Dict[str, Any]]:
    """Fetch models via ``GET /v1/models`` (OpenAI-compatible format).

    Returns a list of dicts with at least ``id`` and optional metadata.
    """
    url = f"http://{host}:{port}/v1/models"
    try:
        resp = requests.get(url, timeout=2)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except (requests.RequestException, OSError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------


def _build_provider_entry(
    api_type: str,
    host: str,
    port: int,
    model_name: str,
    extra_meta: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a single provider entry for the config."""
    safe_host = host.replace(".", "_")
    safe_model = model_name.replace("/", "_").replace(":", "_")
    provider_id = f"{api_type}_{safe_model}_{safe_host}:{port}"

    entry: Dict[str, Any] = {
        "id": provider_id,
        "api_host": f"http://{host}:{port}",
        "api_token": "",
        "api_type": api_type,
        "input_size": 0,
        "model_path": model_name,
        "keep_alive": None,
        "tool_calling": False,
    }

    if extra_meta:
        # Pass through recognised metadata keys.
        for key in ("input_size", "tool_calling"):
            val = extra_meta.get(key)
            if val is not None:
                entry[key] = val
        max_length = extra_meta.get("max_context_length") or extra_meta.get(
            "root_max_window_tokens"
        )
        if max_length and isinstance(max_length, int):
            entry["input_size"] = max_length

    return entry


def _build_config_for_provider(
    provider_def: Dict[str, Any],
    host: str,
    port: int,
) -> Dict[str, Any]:
    """Discover models for one provider and return the config group dict."""
    api_type = provider_def["api_type"]
    group_name = provider_def["group_name"]
    model_name_key = provider_def["model_name_key"]

    is_openai_style = api_type in ("vllm", "lmstudio")

    if is_openai_style:
        raw_models = _fetch_openai_style_models(host, port)
    else:
        raw_models = _fetch_ollama_models(host, port)

    group: Dict[str, Any] = {}
    models_data: Dict[str, Dict[str, Any]] = {"models_raw": raw_models}
    if api_type == "vllm":
        models_data["response_format"] = "openai"
    elif api_type == "lmstudio":
        models_data["response_format"] = "openai"

    for item in raw_models:
        name = item.get(model_name_key, "")
        if not name:
            continue
        # Sanitise model path to avoid spaces/unsafe chars.
        safe_name = name.replace(" ", "_")

        # Collect metadata to pass through to the provider entry.
        extra: Dict[str, Any] | None = None
        if isinstance(item, dict):
            meta_keys = (
                "input_size",
                "tool_calling",
                "context_length",
                "root_max_window_tokens",
                "max_context_length",
            )
            extra = {k: v for k, v in item.items() if k in meta_keys}
            # Ollama sends context_length; normalise to input_size.
            ctx = extra.pop("context_length", None) or extra.pop(
                "max_context_length", None
            )
            if ctx and isinstance(ctx, int):
                extra["input_size"] = ctx

        group[safe_name] = {
            "providers": [
                _build_provider_entry(api_type, host, port, safe_name, extra)
            ],
            "providers_sleep": [],
        }
        group[safe_name].update(models_data)

    return group_name, group


def _clean_config(config: Dict[str, Any]) -> None:
    """Remove internal debug fields from the generated config."""
    for key in list(config.keys()):
        val = config[key]
        if isinstance(val, dict):
            # Clean top-level group entries (e.g. "ollama_models": {...})
            val.pop("models_raw", None)
            val.pop("response_format", None)
            # Also clean per-model sub-entries that may have leaked debug fields
            for mkey in list(val.keys()):
                mval = val[mkey]
                if isinstance(mval, dict):
                    mval.pop("models_raw", None)
                    mval.pop("response_format", None)


def _generate_config(
    hosts: List[Tuple[str, int]], all_ports: bool = False
) -> Dict[str, Any]:
    """Run discovery across all provider definitions for every host

    Each entry in *hosts* is ``(raw_host, explicit_port)`` — when *explicit_port* is
    non-zero only that port is scanned (for ``host:port`` inputs); otherwise the
    default provider ports are used.
    """
    config: Dict[str, Any] = {}

    for host, explicit_port in hosts:
        for prov in _PROVIDER_DEFS:
            # Determine which ports to scan for this provider.
            if explicit_port != 0:
                # Explicit port → use it plus all default provider ports
                # so we don't miss Ollama on :11434 when user only knows about :8080.
                ports_to_scan = [explicit_port] + list(prov["ports"])
            else:
                # No explicit port → just the provider's defaults.
                ports_to_scan = list(prov["ports"])

            # Scan all candidate ports; pick the first one that serves models.
            best_port = None
            for port in ports_to_scan:
                if _health_check_with_path(host, port, prov["health_path"]):
                    group_name_local, group = _build_config_for_provider(
                        prov, host, port
                    )
                    # Check if it actually has models (not just a health endpoint).
                    if group and "models_raw" not in group:
                        best_port = port
                        break

            if best_port is None:
                continue  # provider unreachable on any checked port

            # Build final config entry for the winning port.
            group_name, group = _build_config_for_provider(prov, host, best_port)
            if group_name in config:
                # Merge models by name across hosts — each model gets one provider per
                # (host, port).
                for model_name, model_data in group.items():
                    if model_name not in config[group_name]:
                        config[group_name][model_name] = model_data
                    else:
                        # Add a new provider entry without duplicating (host, port).
                        new_provider = model_data.get("providers", [{}])[0]
                        existing_providers = config[group_name][model_name].get(
                            "providers", []
                        )
                        new_host_port = new_provider.get("api_host", "")
                        if not any(
                            p.get("api_host") == new_host_port
                            for p in existing_providers
                        ):
                            existing_providers.append(new_provider)
            else:
                config[group_name] = group

    # Remove internal debug fields before returning.
    _clean_config(config)
    return config


# ---------------------------------------------------------------------------
# CLI logic
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-router config",
        description=(
            "Auto-discover local LLM providers"
            " (Ollama, vLLM, LM Studio) on a given host,"
            " fetch their available models, and produce"
            " a models-config.json ready for the router."
        ),
    )
    subparsers = parser.add_subparsers(dest="config_action")

    discover_p = subparsers.add_parser(
        "discover",
        help="Scan one or more hosts for local LLM servers and generate config",
    )
    discover_p.add_argument(
        "hosts",
        nargs="+",
        help="Target hosts to scan for local LLM providers.",
    )
    discover_p.add_argument(
        "-o",
        "--config-file",
        dest="config_file",
        default=None,
        help=(
            "Output path for the generated config file. "
            "When omitted (or ``-``), write to stdout."
        ),
    )
    discover_p.add_argument(
        "--all-ports",
        action="store_true",
        default=False,
        help="Check all known ports even if the first one is already reachable.",
    )
    discover_p.add_argument(
        "--no-active",
        action="store_true",
        default=False,
        help="Skip writing the active_models section (produce provider entries only).",
    )

    merge_p = subparsers.add_parser(
        "merge",
        help="Merge multiple models-config.json files into one output file",
    )
    merge_p.add_argument(
        "configs",
        nargs="+",
        help="Input config files to merge (at least one required).",
    )
    merge_p.add_argument(
        "-o",
        "--output",
        dest="config_file",
        default=None,
        help=(
            "Output path for the merged config file. "
            "When omitted (or ``-``), write to stdout."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``llm-router config``.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments after ``config``. Defaults to ``sys.argv[2:]``.

    Returns
    -------
    int
        Exit code (0 on success, 1 on error).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    action = getattr(args, "config_action", None)
    if action == "merge":
        return _do_merge(args)
    return _do_discover(args)


# ---------------------------------------------------------------------------
# Merge subcommand
# ---------------------------------------------------------------------------


def _load_config(path: str) -> Dict[str, Any]:
    """Load a JSON config file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Error reading {path}: {exc}", file=sys.stderr)
        return {}


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *overlay* into *base* (overlay wins on conflict)."""
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _dedup_providers(models_group: Dict[str, Any]) -> None:
    """Deduplicate provider entries (same ``api_host`` → keep first)."""
    for model_name in list(models_group.keys()):
        model_data = models_group[model_name]
        if not isinstance(model_data, dict):
            continue
        providers = model_data.get("providers")
        if not isinstance(providers, list):
            continue
        seen: set[str] = set()
        filtered: list[Dict[str, Any]] = []
        for p in providers:
            host = p.get("api_host", "")
            if host not in seen:
                seen.add(host)
                filtered.append(p)
        model_data["providers"] = filtered


def _do_merge(args: argparse.Namespace) -> int:
    """Merge multiple models-config.json files into one."""
    configs_arg: list[str] = getattr(args, "configs", [])

    merged: Dict[str, Any] = {}
    active: Dict[str, List[str]] = {}

    for cfg_path in configs_arg:
        cfg = _load_config(cfg_path)
        if not cfg:
            continue

        for key, val in cfg.items():
            if key == "active_models":
                # Union all active model lists
                for group, models in val.items():
                    if isinstance(models, list):
                        if group not in active:
                            active[group] = []
                        active[group].extend(models)
            elif isinstance(val, dict):
                merged = _deep_merge(merged, {key: val})

    # Deduplicate providers across all model groups
    for key in merged:
        if isinstance(merged[key], dict):
            _dedup_providers(merged[key])

    active_models: Dict[str, List[str]] = {}
    for group_name, models in merged.items():
        if isinstance(models, dict) and any(
            isinstance(v, dict) and "providers" in v for v in models.values()
        ):
            seen: set[str] = set(active_models.get(group_name, []))
            all_models: List[str] = []
            for name in models.keys():
                if name not in seen:
                    seen.add(name)
                    all_models.append(name)
            active_models[group_name] = all_models

    # Add union from input files
    for group, models in active.items():
        existing = set(active_models.get(group, []))
        for m in models:
            if m not in existing:
                existing.add(m)
        active_models[group] = list(existing)

    merged["active_models"] = active_models

    output_json = json.dumps(merged, indent=2) + "\n"

    out_path: str | None = getattr(args, "config_file", None)
    if out_path and out_path != "-":
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(output_json)
        print(f"Merged config written to {out_path}")
    else:
        sys.stdout.write(output_json)

    return 0


def _do_discover(args: argparse.Namespace) -> int:
    """Shared discovery logic invoked by both the CLI and tests."""
    raw_hosts = getattr(
        args, "hosts", ["localhost"]
    )  # default to localhost when called without positional arg
    hosts: List[Tuple[str, int]] = [_parse_host(h) for h in raw_hosts]
    config = _generate_config(hosts, all_ports=getattr(args, "all_ports", False))

    if not config:
        print(
            f"Warning: no local providers found at {', '.join(raw_hosts)}",
            file=sys.stderr,
        )
        # Still write a minimal empty config.
        config = {}

    # Build active_models from provider groups.
    if not getattr(args, "no_active", False):
        active: Dict[str, List[str]] = {}
        for group_name, models in config.items():
            if isinstance(models, dict) and "models_raw" not in models:
                active[group_name] = list(models.keys())
        config["active_models"] = active

    output_json = json.dumps(config, indent=2) + "\n"

    config_file: str | None = getattr(args, "config_file", None)
    if config_file and config_file != "-":
        with open(config_file, "w", encoding="utf-8") as fh:
            fh.write(output_json)
        print(f"Config written to {config_file}")
    else:
        sys.stdout.write(output_json)

    return 0


def register_config_subparser(
    subparsers: argparse._SubParsersAction, nest_auth: bool = True
) -> None:
    """Register the ``config`` subparser with its child commands.

    Parameters
    ----------
    subparsers : argparse._SubParsersAction
        The parent subparsers action to register under (from top-level CLI).
    nest_auth : bool
        Ignored for config (flat subcommand). Kept for API consistency.
    """
    # The ``config`` command has a single subcommand ``discover``.
    # ``subparsers`` here is already the parent subparsers action (e.g. from
    # top-level CLI), so we register "discover" directly under it.
    discover_parser = subparsers.add_parser(
        "discover",
        help="Scan one or more hosts for local LLM servers and generate config",
    )

    discover_parser.add_argument(
        "hosts",
        nargs="+",
        help="Target hosts to scan for local LLM providers.",
    )
    discover_parser.add_argument(
        "-o",
        "--config-file",
        dest="config_file",
        default=None,
        help=(
            "Output path for the generated config file. "
            "When omitted (or ``-``), write to stdout."
        ),
    )
    discover_parser.add_argument(
        "--all-ports",
        action="store_true",
        default=False,
        help="Check all known ports even if the first one is already reachable.",
    )
    discover_parser.add_argument(
        "--no-active",
        action="store_true",
        default=False,
        help="Skip writing the active_models section (produce provider entries only).",
    )

    # -- merge subcommand --------------------------------------------------
    merge_parser = subparsers.add_parser(
        "merge",
        help="Merge multiple models-config.json files into one output file",
    )
    merge_parser.add_argument(
        "configs",
        nargs="+",
        help="Input config files to merge (at least one required).",
    )
    merge_parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=None,
        help=(
            "Output path for the merged config file. "
            "When omitted (or ``-``), write to stdout."
        ),
    )
