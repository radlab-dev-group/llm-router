#!/usr/bin/env bash
set -euo pipefail

# Run the agentic-knowledge indexing worker.
#
# The worker is the write half of the knowledge layer: it consumes the
# knowledge events the router publishes to the Redis stream, masks them and
# indexes them into the Semantic Search Engine, and creates a repository's
# collection the first time that repository produces knowledge.  It is a
# separate process from the router on purpose: indexing is slow (an embedder
# and a reranker per document) and must not block a live request.
#
# The environment — SSE, Redis and the worker's own knobs — comes from the
# router's run script, so both halves of the layer are configured in one
# place.  That script is read, not executed: only its configuration lines are
# evaluated, so the router server never starts.
#
#   bash run-agentic-kb-worker.sh [ROUTER_SCRIPT] [worker options...]
#
# With no ROUTER_SCRIPT the run-rest-api-gunicorn.sh next to this script is used.  The worker options (--config, --once,
# --no-retain, --log-level) are passed through; the knowledge policy itself is
# read the way the router reads it, from LLM_ROUTER_KNOWLEDGE_AGENTIC_CONFIG or
# the bundled policy.

if [ -n "${1:-}" ] && [ -f "${1:-}" ]; then
    ROUTER_SCRIPT="$1"
    shift
else
    ROUTER_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run-rest-api-gunicorn.sh"
fi
[ -f "$ROUTER_SCRIPT" ] || { echo "router script not found: $ROUTER_SCRIPT" >&2; exit 1; }

# The configuration part of the router script: its variable assignments, up to
# the point where it stops configuring and starts the server (a function
# definition or the server command).  Comments, blank lines and `set` are not
# configuration and are dropped.
CONFIG=$(awk '
    /^[[:space:]]*(function[[:space:]]|[a-z-]*llm-router[[:space:]])/ { exit }
    /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=/ { print }
' "$ROUTER_SCRIPT")
# shellcheck disable=SC2086
set -a; eval "$CONFIG"; set +a

# The worker is this package's console command, installed with the
# ``agentic-knowledge`` extra (which is what brings in sse_lib):
#   pip install "radlab-llm-router-plugins[agentic-knowledge]"
# Point KB_WORKER at a virtual environment's command when the one on PATH is
# not the installation this deployment runs, e.g.
#   KB_WORKER=.venv/bin/llm-router-agentic-kb-worker bash run-agentic-kb-worker.sh
KB_WORKER=${KB_WORKER:-llm-router-agentic-kb-worker}

if ! command -v "$KB_WORKER" >/dev/null 2>&1; then
    echo "knowledge worker command not found: $KB_WORKER" >&2
    echo "install it with: pip install \"radlab-llm-router-plugins[agentic-knowledge]\"" >&2
    exit 1
fi

exec "$KB_WORKER" "$@"
