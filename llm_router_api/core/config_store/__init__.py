"""
Configuration source factory -- selects the concrete backend based on ``source_type``.

Usage::

    from llm_router_api.core.config_store import create_config_source

    if config_source == "etcd":
        source = create_config_source("etcd",
            host=os.environ.get("LLM_ROUTER_ETCD_HOST", "127.0.0.1"),
            port=int(os.environ.get("LLM_ROUTER_ETCD_PORT", "2379")),
            key=os.environ.get("LLM_ROUTER_ETCD_CONFIG_KEY", "/llm-router/models-config"),
        )
    else:
        source = create_config_source("file", path=MODELS_CONFIG_FILE)
"""

from __future__ import annotations

from typing import Any

from .interface import ConfigSourceI


# Lazy detection of etcd3 availability
_ETCD_AVAILABLE = False
try:
    import etcd3  # noqa: F401  # pylint: disable=unused-import

    _ETCD_AVAILABLE = True
except ImportError:
    pass


def create_config_source(
    source_type: str = "file",
    **kwargs: Any,
) -> ConfigSourceI:
    """
    Create a configuration source instance.

    Parameters
    ----------
    source_type : str
        One of ``"file"`` or ``"etcd"``.
    **kwargs
        Backend-specific parameters forwarded to the constructor.

    Returns
    -------
    ConfigSourceI
        The instantiated config source.

    Raises
    ------
    RuntimeError
        If etcd is requested but the etcd3 library is not installed.
    ValueError
        If ``source_type`` is unrecognized.
    """
    if source_type == "file":
        from .file_source import FileConfigSource

        path = kwargs.get("path", "resources/configs/models-config.json")  # type: ignore[arg-type]
        return FileConfigSource(path=path)

    if source_type == "etcd":
        if not _ETCD_AVAILABLE:
            raise RuntimeError(
                "etcd3 is not installed. Install it with: "
                "pip install llm-router[etcd]"
            )
        from .etcd_source import EtcdConfigSource

        return EtcdConfigSource(
            host=kwargs.get("host", "127.0.0.1"),  # type: ignore[arg-type]
            port=int(kwargs.get("port", 2379)),  # type: ignore[arg-type]
            key=kwargs.get("key", "/llm-router/models-config"),  # type: ignore[arg-type]
            ca_cert=kwargs.get("ca_cert"),
            cert=kwargs.get("cert"),
            key_priv=kwargs.get("key_priv"),
        )

    raise ValueError(f"Unknown config source type: {source_type}")


__all__ = ["create_config_source", "ConfigSourceI", "ConfigState"]
