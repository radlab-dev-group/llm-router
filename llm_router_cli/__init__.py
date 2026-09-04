"""
llm-router Python packages.
"""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__: str = _version("llm-router")
except PackageNotFoundError:
    # Running from a bare checkout without an installed distribution.
    __version__ = "0.0.0+local"
