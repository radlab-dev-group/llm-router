from pathlib import Path
from setuptools import setup, find_packages

BASE_DIR = Path(__file__).parent

# ----------------------------------------------------------------------
# Core version & requirements (the library itself)
# ----------------------------------------------------------------------
version = (BASE_DIR / ".version").read_text().strip()
long_description = (BASE_DIR / "README.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# API‑specific requirements
# ----------------------------------------------------------------------


def _read_requirements(path: Path) -> list:
    """
    Read a requirements file into a list of PEP 508 specifiers.

    Blank lines, full-line comments and trailing ``# comment`` fragments are
    stripped so the result is safe to use directly as ``install_requires`` /
    ``extras_require`` entries (``pip install .[api]`` must never see a
    comment string).
    """
    reqs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith("#"):
            reqs.append(line)
    return reqs


requirements_api = _read_requirements(BASE_DIR / "requirements.txt")

# ----------------------------------------------------------------------
# Extras handling
# ----------------------------------------------------------------------
extras = {
    "api": requirements_api,
    "metrics": ["prometheus-client"],  # prometheus-client==0.21.0
    "vault": ["hvac", "bcrypt"],  # "hvac==2.3.0", "bcrypt==5.0.0"
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
        # Exclude test & doc sub-packages so they never ship in the wheel.
        exclude=(
            "tests",
            "tests.*",
            "docs",
            "docs.*",
            "llm_router_lib.tests",
            "llm_router_lib.tests.*",
            "llm_router_api.tests",
            "llm_router_api.tests.*",
            "llm_router_cli.tests",
            "llm_router_cli.tests.*",
        ),
    ),
    package_data={
        "llm_router_cli.resources": ["configs/*.json"],
    },
    python_requires=">=3.10",
    install_requires=[
        "ml-utils @ " "git+https://github.com/radlab-dev-group/ml-utils.git",
        "llm-router-plugins @ "
        "git+https://github.com/radlab-dev-group/llm-router-plugins",
    ],
    extras_require=extras,
    entry_points={
        "console_scripts": {
            "llm-router=llm_router_cli.cli:main",
        }
    },
)
