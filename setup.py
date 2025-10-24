from pathlib import Path
from setuptools import setup, find_packages

BASE_DIR = Path(__file__).parent

# ----------------------------------------------------------------------
# Core version & requirements (the library itself)
# ----------------------------------------------------------------------
version = (BASE_DIR / ".version").read_text().strip()
requirements_lib = (BASE_DIR / "requirements_lib.txt").read_text().splitlines()

# ----------------------------------------------------------------------
# API‑specific requirements
# ----------------------------------------------------------------------
requirements_api = (BASE_DIR / "requirements.txt").read_text().splitlines()

# ----------------------------------------------------------------------
# Extras handling
# ----------------------------------------------------------------------
extras = {
    "api": requirements_api,
    "metrics": ["prometheus-client"],
}


# ----------------------------------------------------------------------
setup(
    name="llm-router",
    version=version,
    author="RadLab team",
    description="LLM Router – core library with optional API and metrics",
    packages=find_packages(
        where=".",
        include=["llm_router_lib*", "llm_router_api*"],
        exclude=("tests", "docs"),
    ),
    python_requires=">=3.10",
    install_requires=requirements_lib,
    extras_require=extras,
    entry_points={},
)
