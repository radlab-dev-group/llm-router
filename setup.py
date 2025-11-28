from pathlib import Path
from setuptools import setup, find_packages

BASE_DIR = Path(__file__).parent

# ----------------------------------------------------------------------
# Core version & requirements (the library itself)
# ----------------------------------------------------------------------
version = (BASE_DIR / ".version").read_text().strip()
long_description = (BASE_DIR / "README.md").read_text(encoding="utf-8")
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
    description="LLM Router – core library with optional API and metrics",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="RadLab.dev Team",
    url="https://github.com/radlab-dev-group/llm-router",
    license="Apache-2.0",
    packages=find_packages(
        where=".",
        include=[
            "llm_router_lib*",
            "llm_router_api*",
            "llm_router_cli*",
        ],
        exclude=("tests", "docs"),
    ),
    python_requires=">=3.10",
    install_requires=requirements_lib
    + [
        "radlab-ml-utils @ git+https://github.com/radlab-dev-group/ml-utils",
        "llm-router-plugins @ git+https://github.com/radlab-dev-group/llm-router-plugins",
    ],
    extras_require=extras,
    entry_points={
        "console_scripts": {
            "llm-router-fast-masker=llm_router_cli.fast_masker:main",
        }
    },
)
