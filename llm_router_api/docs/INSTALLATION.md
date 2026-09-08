# Installation

Three ways to get **LLM Router** running: from **PyPI** (recommended), from the **GitHub**
source repository, or as a pre-built **Docker image on Quay**.

Requires **Python ≥ 3.10**.

---

## 1. PIP (recommended)

The package is published on PyPI:
[radlab-llm-router](https://pypi.org/project/radlab-llm-router/).

### Create & activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### Install

```shell
# Only the core library (llm_router_lib).
pip install radlab-llm-router

# Core library + API wrapper (llm_router_api).
pip install radlab-llm-router[api]

# Core library + API wrapper + Prometheus metrics.
pip install radlab-llm-router[api,metrics]
```

### Extras

| Extra     | Adds                                        |
|-----------|---------------------------------------------|
| `api`     | The REST API wrapper (`llm_router_api`)     |
| `metrics` | Prometheus metrics (`prometheus-client`)    |
| `vault`   | HashiCorp Vault integration (`hvac`, `bcrypt`) |

> **Note:** When Prometheus metrics are enabled, `LLM_ROUTER_USE_PROMETHEUS=1`
> must be set and **Redis is required** (used for provider availability state).
> The multiproc directory defaults to
> `$HOME/.llm-router/metrics/prometheus/multiproc` — override via the
> `PROMETHEUS_MULTIPROC_DIR` environment variable if needed.

---

## 2. GitHub (from source)

Installing from source pulls the latest code from the
[llm-router repository](https://github.com/radlab-dev-group/llm-router) —
prefer PyPI for production deployments.

### Option A — clone & install locally

```shell
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router

python3 -m venv .venv
source .venv/bin/activate

# Only the core library (llm_router_lib).
pip install .

# Core library + API wrapper (llm_router_api).
pip install .[api]

# Core library + API wrapper + Prometheus metrics.
pip install .[api,metrics]
```

### Option B — install directly from the git URL (no clone)

```shell
# Pin a release tag (e.g. v1.0.5):
pip install "git+https://github.com/radlab-dev-group/llm-router@v1.0.5"

# With extras:
pip install "git+https://github.com/radlab-dev-group/llm-router@v1.0.5#[api]"
```

> **Note:** `@main` tracks the repository HEAD and may contain unreleased,
> unstable changes — always pin a release tag for reproducible installs.

---

## 3. Quay (Docker image)

A pre-built container image is available on
[Quay](https://quay.io/repository/radlab/llm-router): `quay.io/radlab/llm-router`.

### Quick start

```shell
docker pull quay.io/radlab/llm-router:rc1
docker run -p 5555:8080 quay.io/radlab/llm-router:rc1
```

### Advanced usage

All runtime settings are configured via `LLM_ROUTER_*` environment variables —
see the [Docker section of the README](../../README.md#-docker) for the full
custom launch-script example (server type, timeouts, balance strategy, Redis,
models config mount, …), and
[ENV_DEFINITIONS.md](ENV_DEFINITIONS.md) for the complete variable reference.

### Kubernetes (Helm)

Helm charts for Kubernetes deployment are available in the
[`helm_charts/`](../../helm_charts/) directory.
