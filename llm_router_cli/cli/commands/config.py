"""
CLI commands for generating a models-config.json from auto-discovered local providers.

Usage::

    llm-router config discover localhost --output-config-file generated-config.json
    llm-router config discover localhost 192.168.1.50 10.0.0.1
"""

from __future__ import annotations

import sys
import json
import argparse
import requests

from typing import Any, Dict, List, Optional, Set, Tuple

from .base import BaseCommand


class ConfigCommand(BaseCommand):
    """Encapsulates the ``config`` CLI subcommand and all its children."""

    NAME = "config"
    HELP = "Auto-discover local providers and generate/merge models-config.json"
    SUBPARSER_DEST = "config_command"

    DISCOVER_HELP = (
        "Scan one or more hosts for local LLM servers and generate config"
    )
    MERGE_HELP = "Merge multiple models-config.json files into one output file"

    # ---- Provider registry (class-level constant) -------------------------

    PROVIDER_DEFINITIONS: List[Dict[str, Any]] = [
        {
            "api_type": "ollama",
            "group_name": "ollama_models",
            "ports": [11434, 18765],
            "health_path": "/",
            "models_path": "/api/tags",
            "fetch_type": "ollama",
            "model_name_key": "id",
            "tool_calling_hint": False,
        },
        {
            "api_type": "vllm",
            "group_name": "vllm_models",
            "ports": [8000, 7000],
            "health_path": "/health",
            "models_path": "/v1/models",
            "fetch_type": "openai_style",
            "model_name_key": "id",
            "tool_calling_hint": True,
        },
        {
            "api_type": "lmstudio",
            "group_name": "lmstudio_models",
            "ports": [1234, 1235],
            "health_path": "/",
            "models_path": "/v1/models",
            "fetch_type": "openai_style",
            "model_name_key": "id",
            "tool_calling_hint": True,
        },
        {
            "api_type": "llamacpp",
            "group_name": "llamacpp_models",
            "ports": [8080],
            "health_path": "/health",
            "models_path": "/v1/models",
            "fetch_type": "openai_style",
            "model_name_key": "id",
            "tool_calling_hint": True,
        },
        {
            "api_type": "koboldcpp",
            "group_name": "koboldcpp_models",
            "ports": [5001],
            "health_path": "/",
            "models_path": "/api/v1/models",
            "fetch_type": "openai_style",
            "model_name_key": "id",
            "tool_calling_hint": True,
        },
        {
            "api_type": "tabbyapi",
            "group_name": "tabbyapi_models",
            "ports": [8080],
            "health_path": "/health",
            "models_path": "/v1/models",
            "fetch_type": "openai_style",
            "model_name_key": "id",
            "tool_calling_hint": True,
        },
    ]

    # ---- Argument-adding helpers -------------------------------------------

    @staticmethod
    def _add_discover_args(p: argparse.ArgumentParser) -> None:
        """
        Add the shared arguments for the ``discover`` subcommand.
        """
        p.add_argument(
            "hosts", nargs="+", help="Target hosts to scan for local LLM providers."
        )
        p.add_argument(
            "-o",
            "--output-config-file",
            dest="output_config_file",
            default=None,
            help="Output path for the generated config file. "
            "When omitted (or ``-``), write to stdout.",
        )
        p.add_argument(
            "--all-ports",
            action="store_true",
            default=False,
            help="Check all known ports even if the first one is already reachable.",
        )
        p.add_argument(
            "--no-active",
            action="store_true",
            default=False,
            help="Skip writing the active_models section "
            "(produce provider entries only).",
        )

    @staticmethod
    def _add_merge_args(p: argparse.ArgumentParser) -> None:
        """
        Add the shared arguments for the ``merge`` subcommand.
        """
        p.add_argument(
            "configs",
            nargs="+",
            help="Input config files to merge (at least one required).",
        )
        p.add_argument(
            "-o",
            "--output-config-file",
            dest="output_config_file",
            default=None,
            help="Output path for the merged config file. "
            "When omitted (or ``-``), write to stdout.",
        )

    # ---- Host parsing / utilities ------------------------------------------

    @staticmethod
    def _parse_host(raw: str) -> Tuple[str, int, str]:
        """
        Split ``host:port`` into ``(host, port, protocol)``.
        """
        protocol = "http"
        scheme_end = raw.find("://")
        if scheme_end != -1:
            protocol = raw[:scheme_end]
            raw = raw[scheme_end + 3 :]

        if raw.startswith("["):
            end = raw.find("]")
            if end != -1 and ":" in raw[end + 1 :]:
                host_port = raw[end + 1 :]
                port_str = host_port.lstrip(":")
                return raw[1:end], int(port_str), protocol
            return raw, 0, protocol

        if raw.count(":") <= 1:
            parts = raw.rsplit(":", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return parts[0], int(parts[1]), protocol
            return raw, 0, protocol

        return raw, 0, protocol

    @staticmethod
    def _sanitize(name: str) -> str:
        """
        Sanitize a model name / path for safe use as an identifier key.
        """
        return name.replace("/", "_").replace(":", "_").replace(" ", "_")

    # ---- Registration ------------------------------------------------------

    @classmethod
    def register_children(
        cls, subparsers: "argparse._SubParsersAction[Any]"
    ) -> None:
        """Register the ``config`` leaf subcommands (discover / merge)."""
        discover_p = subparsers.add_parser("discover", help=cls.DISCOVER_HELP)
        cls._add_discover_args(discover_p)

        merge_p = subparsers.add_parser("merge", help=cls.MERGE_HELP)
        cls._add_merge_args(merge_p)

    # ---- Dispatch ----------------------------------------------------------

    @classmethod
    def dispatch(cls, args: argparse.Namespace) -> int:
        """Route on the parsed namespace (no re-parsing of ``argv``)."""
        action = getattr(args, cls.SUBPARSER_DEST, None)
        if action == "merge":
            return cls._do_merge(args)
        if action == "discover":
            return cls._do_discover(args)
        cls.build_parser().print_help()
        return 0

    @staticmethod
    def _get_flag(args: argparse.Namespace, name: str, default: bool) -> bool:
        """
        Safely read a boolean CLI flag, falling back to *default*.
        """
        return bool(getattr(args, name, default))

    # ---- Discovery helpers -------------------------------------------------

    @staticmethod
    def _health_check(
        host: str,
        port: int,
        path: str = "/",
        timeout: float = 0.5,
        protocol: str = "http",
    ) -> bool:
        """
        Return True when a HTTP service responds on
        ``{protocol}://{host}:{port}{path}``.
        """
        try:
            resp = requests.get(f"{protocol}://{host}:{port}{path}", timeout=timeout)
            return resp.status_code < 500
        except (requests.RequestException, OSError):
            return False

    @staticmethod
    def _get_json(url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
        """
        Fetch *url* and decode it as a JSON object, or ``None`` on any
        network/parse failure.
        """
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def _fetch_ollama_models(
        cls, host: str, port: int, protocol: str = "http"
    ) -> List[Dict[str, Any]]:
        """
        Fetch Ollama model info via ``GET /api/tags``.
        """
        data = cls._get_json(f"{protocol}://{host}:{port}/api/tags")
        if data is None:
            return []
        models: List[Dict[str, Any]] = []
        for m in data.get("models", []):
            name = m.get("name")
            if not name:
                continue
            detail = m.get("details", {})
            top_caps = set(m.get("capabilities") or [])
            det_caps = set(detail.get("capabilities") or []) | set(
                detail.get("families") or []
            )
            all_caps = top_caps | det_caps
            models.append(
                {
                    "id": name,
                    "context_length": detail.get("context_length"),
                    "tool_calling": any(
                        kw in all_caps
                        for kw in ("tools", "tool_use", "function_call")
                    ),
                }
            )
        return models

    @classmethod
    def _fetch_openai_style_models(
        cls, host: str, port: int, protocol: str = "http"
    ) -> List[Dict[str, Any]]:
        """
        Fetch models via ``GET /v1/models`` (OpenAI-compatible format).
        """
        data = cls._get_json(f"{protocol}://{host}:{port}/v1/models")
        if data is None:
            return []
        models = data.get("data", [])
        return models if isinstance(models, list) else []

    # ---- Config builder helpers ---------------------------------------------

    @staticmethod
    def _build_provider_entry(
        api_type: str,
        host: str,
        port: int,
        model_name: str,
        extra_meta: Optional[Dict[str, Any]] = None,
        protocol: str = "http",
    ) -> Dict[str, Any]:
        """
        Build a single provider entry for the config.
        """
        safe_model = ConfigCommand._sanitize(model_name)
        safe_host = ConfigCommand._sanitize(host).replace(":", "_")
        provider_id = f"{api_type}_{safe_model}_{safe_host}:{port}"

        entry: Dict[str, Any] = {
            "id": provider_id,
            "api_host": f"{protocol}://{host}:{port}",
            "api_token": "",
            "api_type": api_type,
            "input_size": 0,
            "model_path": safe_model,
            "keep_alive": None,
            "tool_calling": False,
        }

        if extra_meta:
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

    @staticmethod
    def _build_config_for_provider(
        provider_def: Dict[str, Any], host: str, port: int, protocol: str = "http"
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Discover models for one provider and return the config group dict.
        """
        api_type = provider_def["api_type"]
        group_name = provider_def["group_name"]
        model_name_key = provider_def["model_name_key"]
        is_openai_style = provider_def.get("fetch_type") == "openai_style"

        raw_models = (
            ConfigCommand._fetch_openai_style_models(host, port, protocol)
            if is_openai_style
            else ConfigCommand._fetch_ollama_models(host, port, protocol)
        )

        group: Dict[str, Any] = {}
        models_data: Dict[str, Any] = {"models_raw": raw_models}
        if api_type == "vllm":
            models_data["response_format"] = "openai"
        elif api_type == "lmstudio":
            models_data["response_format"] = "openai"

        for item in raw_models:
            name = item.get(model_name_key, "")
            if not name:
                continue
            safe_name = ConfigCommand._sanitize(name)

            extra: Optional[Dict[str, Any]] = None
            if isinstance(item, dict):
                meta_keys = (
                    "input_size",
                    "tool_calling",
                    "context_length",
                    "root_max_window_tokens",
                    "max_context_length",
                )
                extra = {k: v for k, v in item.items() if k in meta_keys}
                ctx = extra.pop("context_length", None) or extra.pop(
                    "max_context_length", None
                )
                if ctx and isinstance(ctx, int):
                    extra["input_size"] = ctx

            group[safe_name] = {
                "providers": [
                    ConfigCommand._build_provider_entry(
                        api_type, host, port, safe_name, extra, protocol
                    )
                ],
                "providers_sleep": [],
            }
            group[safe_name].update(models_data)

        return group_name, group

    @staticmethod
    def _strip_debug_fields(obj: Any) -> None:
        """
        Recursively remove internal debug fields from *obj* (in-place).
        """
        if isinstance(obj, dict):
            for key in list(obj.keys()):
                val = obj[key]
                if key in ("models_raw", "response_format"):
                    obj.pop(key)
                elif isinstance(val, (dict, list)):
                    ConfigCommand._strip_debug_fields(val)
        elif isinstance(obj, list):
            for item in obj:
                ConfigCommand._strip_debug_fields(item)

    @classmethod
    def _scan_and_merge(
        cls,
        host: str,
        explicit_port: int,
        protocol: str,
        prov: Dict[str, Any],
        config: Dict[str, Any],
        collect_all: bool = False,
    ) -> None:
        """
        Discover one provider on one host and merge its config into *config*.

        When *collect_all* is set, every healthy port is accumulated;
        otherwise the first healthy port with a non‑empty model group wins.
        """
        ports_to_scan = [explicit_port] if explicit_port else list(prov["ports"])
        groups: List[Dict[str, Any]] = []
        for port in ports_to_scan:
            if not cls._health_check(
                host, port, path=prov["health_path"], protocol=protocol
            ):
                continue
            _, group = cls._build_config_for_provider(prov, host, port, protocol)
            if group and "models_raw" not in group:
                groups.append(group)
            if groups and not collect_all:
                break
        for group in groups:
            cls._accumulate_group(config, prov["group_name"], group)

    @staticmethod
    def _accumulate_group(
        config: Dict[str, Any], group_name: str, group: Dict[str, Any]
    ) -> None:
        """
        Merge *group* into *config*, deduplicating providers by (host, port).
        """
        if group_name in config:
            for model_name, model_data in group.items():
                if model_name not in config[group_name]:
                    config[group_name][model_name] = model_data
                else:
                    ConfigCommand._add_provider_to_model(
                        config[group_name][model_name], model_data
                    )
        else:
            config[group_name] = group

    @staticmethod
    def _add_provider_to_model(
        existing_model: Dict[str, Any], new_model: Dict[str, Any]
    ) -> None:
        """
        Add *new_model* provider to *existing_model* without duplicating host.
        """
        new_provider = new_model.get("providers", [{}])[0]
        existing_providers = existing_model.get("providers", [])
        new_host_port = new_provider.get("api_host", "")
        if not any(p.get("api_host") == new_host_port for p in existing_providers):
            existing_providers.append(new_provider)

    @classmethod
    def _generate_config(
        cls, hosts: List[Tuple[str, int, str]], all_ports: bool = False
    ) -> Dict[str, Any]:
        """
        Run discovery across all provider definitions for every host.
        """
        config: Dict[str, Any] = {}
        for host, explicit_port, protocol in hosts:
            for prov in ConfigCommand.PROVIDER_DEFINITIONS:
                cls._scan_and_merge(
                    host,
                    explicit_port,
                    protocol,
                    prov,
                    config,
                    collect_all=all_ports,
                )
        ConfigCommand._strip_debug_fields(config)
        return config

    # ---- Merge subcommand helpers ------------------------------------------

    @staticmethod
    def _load_config(path: str) -> Dict[str, Any]:
        """
        Load a JSON config file.
        """
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Error reading {path}: {exc}", file=sys.stderr)
            return {}
        if not isinstance(data, dict):
            print(f"Error reading {path}: expected a JSON object.", file=sys.stderr)
            return {}
        return data

    @staticmethod
    def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively merge *overlay* into *base* (overlay wins on conflict).
        """
        result = dict(base)
        for key, val in overlay.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(val, dict)
            ):
                result[key] = ConfigCommand._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    @staticmethod
    def _dedup_providers(models_group: Dict[str, Any]) -> None:
        """
        Deduplicate provider entries (same ``api_host`` → keep first).
        """
        for model_name in list(models_group.keys()):
            model_data = models_group[model_name]
            if not isinstance(model_data, dict):
                continue
            providers = model_data.get("providers")
            if not isinstance(providers, list):
                continue
            seen: Set[str] = set()
            filtered: List[Dict[str, Any]] = []
            for p in providers:
                host = p.get("api_host", "")
                if host not in seen:
                    seen.add(host)
                    filtered.append(p)
            model_data["providers"] = filtered

    @staticmethod
    def _merge_active_models(val: Any, active: Dict[str, List[str]]) -> None:
        """
        Union all active model lists from *val* into *active*.
        """
        if not isinstance(val, dict):
            return
        for group, models in val.items():
            if isinstance(models, list):
                if group not in active:
                    active[group] = []
                active[group].extend(models)

    # ---- Output / active-models helpers -----------------------------------

    @staticmethod
    def _active_models_from(config: Dict[str, Any]) -> Dict[str, List[str]]:
        """Derive the ``active_models`` mapping (group -> ordered model names)."""
        active: Dict[str, List[str]] = {}
        for group_name, models in config.items():
            if not isinstance(models, dict):
                continue
            if any(
                isinstance(v, dict) and "providers" in v for v in models.values()
            ):
                active[group_name] = list(models.keys())
        return active

    @staticmethod
    def _write_output(
        data: Dict[str, Any], output_file: Optional[str], label: str
    ) -> int:
        """Serialize *data* (JSON) and write it to *output_file* or stdout."""
        output_json = json.dumps(data, indent=2) + "\n"
        if output_file and output_file != "-":
            try:
                with open(output_file, "w", encoding="utf-8") as fh:
                    fh.write(output_json)
                print(f"{label} written to {output_file}")
            except OSError as exc:
                print(f"Error writing {output_file}: {exc}", file=sys.stderr)
                return 1
        else:
            sys.stdout.write(output_json)
        return 0

    # ---- Dispatch helpers ---------------------------------------------------

    @classmethod
    def _do_discover(cls, args: argparse.Namespace) -> int:
        """
        Shared discovery logic invoked by both the CLI and tests.
        """
        raw_hosts = getattr(args, "hosts", ["localhost"])
        hosts: List[Tuple[str, int, str]] = [cls._parse_host(h) for h in raw_hosts]
        config = cls._generate_config(
            hosts, all_ports=ConfigCommand._get_flag(args, "all_ports", False)
        )

        if not config:
            print(
                f"Warning: no local providers found at {', '.join(raw_hosts)}",
                file=sys.stderr,
            )

        if not cls._get_flag(args, "no_active", False):
            config["active_models"] = cls._active_models_from(config)

        return cls._write_output(
            config, getattr(args, "output_config_file", None), "Config"
        )

    @classmethod
    def _do_merge(cls, args: argparse.Namespace) -> int:
        """
        Merge multiple models-config.json files into one.
        """
        configs_arg: List[str] = getattr(args, "configs", [])

        merged: Dict[str, Any] = {}
        active: Dict[str, List[str]] = {}
        failures: List[str] = []

        for cfg_path in configs_arg:
            cfg = ConfigCommand._load_config(cfg_path)
            if not cfg:
                failures.append(cfg_path)
                continue
            for key, val in cfg.items():
                if key == "active_models":
                    ConfigCommand._merge_active_models(val, active)
                elif isinstance(val, dict):
                    merged = ConfigCommand._deep_merge(merged, {key: val})

        if failures:
            for fp in failures:
                print(f"Warning: skipped unreadable file {fp}", file=sys.stderr)

        for _key, _group in merged.items():
            if isinstance(_group, dict):
                ConfigCommand._dedup_providers(_group)

        active_models = ConfigCommand._active_models_from(merged)
        for group, models in active.items():
            existing = set(active_models.get(group, []))
            for m in models:
                if m not in existing:
                    existing.add(m)
            active_models[group] = list(existing)

        merged["active_models"] = active_models

        return ConfigCommand._write_output(
            merged, getattr(args, "output_config_file", None), "Merged config"
        )
