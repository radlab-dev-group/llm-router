# llm-proxy-api

A lightweight, extensible gateway that exposes a clean REST API 
to interact with various Large Language Models (LLMs).

## Features
- Unified REST interface for multiple LLM providers
- Built-in request validation
- Pluggable prompts and models configuration
- Structured logging with configurable level and file
- Simple deployment via a single run script

## Quick start

1) Create and activate virtualenv

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Minimum required environment

```bash
export LLM_PROXY_API_MINIMUM=1
```

3) Optional configuration

```bash
# Logging
export LLM_PROXY_API_LOG_FILENAME="llm-proxy-rest.log"

# DEBUG/INFO/WARN/ERROR
export LLM_PROXY_API_LOG_LEVEL="INFO"   

# API behavior
export LLM_PROXY_API_TIMEOUT=300        # seconds
export LLM_PROXY_API_EP_PREFIX="/api"   # default prefix

# Language for built-in prompts (when applicable)
export LLM_PROXY_API_DEFAULT_EP_LANGUAGE="pl"

# Paths
export LLM_PROXY_API_PROMPTS_DIR="resources/prompts"
# Models configuration file
# (JSON with model/provider configuration expected by the service)
# If not set, defaults to resources/configs/models-config.json
```

4) Run the REST API
```bash
./run-rest-api.sh
# or
LLM_PROXY_API_MINIMUM=1 python3 -m llm_proxy_rest.rest_api
```

## Endpoints (high level)

- `POST /api/chat`  
  Chat-style conversation with a model. Accepts validated payload and returns model response.

- `POST /api/conversation_with_model`  
  Conversation with built-in system prompt (language-aware).

- `POST /api/extended_conversation_with_model`  
  Extended request format with richer options.

- `GET /api/tags`  
  Returns available tags/metadata.

Note: Exact request/response schemas are validated and errors are returned when parameters are invalid.

## Configuration overview

- Prompts directory: `resources/prompts` (override with `LLM_PROXY_API_PROMPTS_DIR`)
- Models config: `resources/configs/models-config.json` (override with env)
- API prefix: `/api` (`LLM_PROXY_API_EP_PREFIX`)
- Timeout: `300s` (`LLM_PROXY_API_TIMEOUT`)
- Logs: file name and level configurable via env; `DEBUG` when `LLM_PROXY_API_IN_DEBUG` is true

## Development

- Python 3.10+
- Install deps from requirements.txt inside a virtualenv

## License
See [LICENSE](LICENSE)

## Changelog
See [CHANGELOG](CHANGELOG.md).

