"""
llm-router Python packages.
"""

from importlib.metadata import PackageNotFoundError, version as _version

from llm_router_lib.core.constants import PACKAGE_NAME

try:
    __version__: str = _version(PACKAGE_NAME)
except PackageNotFoundError:
    # Running from a bare checkout without an installed distribution.
    __version__ = "0.0.0+local"
