#!/usr/bin/env bash
set -euo pipefail

# Publish one or more repositories' documentation to the agentic knowledge stream.
#
# The proxy indexes a repository's markdown on the first request made in it, which is the right
# default and the wrong tool for a cold start: this command scans the same directories, under the
# same policy, and publishes the same `doc` events — it reads files and publishes to the stream,
# so it never talks to the search engine and needs no agent to be involved.
#
# The worker has to be running: this command publishes, that one masks and indexes. A directory
# published while no worker consumes the stream is not lost — the events wait in the stream — but
# nothing is searchable until the worker reads them.
#
# The environment (SSE, Redis, the docs policy) comes from the router's run script, so both halves
# of the layer are configured in one place. That script is read, not executed: only its
# configuration lines are evaluated, so the router server never starts.
#
#   bash run-agentic-kb-docs.sh [options] DIRECTORY [DIRECTORY...]
#
# Options: --dry-run (list what would be published, publish nothing), --no-prune (keep superseded
# documents), --force (replace queued docs and republish all files), --config FILE, --log-level LEVEL,
# --scope NAME (one directory only).
# Pause workers and other publishers for the selected scopes before --force; restart them afterwards.
# This replaces documentation events in Redis, not the SSE collections. --force --dry-run only previews.
#
# Every directory is indexed into the scope a request made in it would derive — the repository's
# basename unless the policy overrides it — so pass the directory the agent opens as its working
# directory, not a subdirectory of it: `~/dev/webapp` is `webapp`, and `~/dev/webapp/docs` is
# `docs`, a collection no agent will ever read. Run --dry-run first to see the scope and the
# sections before anything is published:
#
#   bash run-agentic-kb-docs.sh --dry-run ~/dev/webapp ~/dev/api
#   bash run-agentic-kb-docs.sh ~/dev/webapp ~/dev/api
#   bash run-agentic-kb-docs.sh --force ~/dev/webapp ~/dev/api
#
# ROUTER_SCRIPT picks the script to read the environment from; KB_DOCS the ``llm-router-agentic-kb-docs``
# command to run, when the one on PATH is not the installation this deployment uses.

if [ -n "${1:-}" ] && [ -f "${1:-}" ]; then
    ROUTER_SCRIPT="$1"
    shift
else
    ROUTER_SCRIPT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)/run-rest-api-gunicorn.sh"
fi
[ -f "$ROUTER_SCRIPT" ] || { echo "router script not found: $ROUTER_SCRIPT" >&2; exit 1; }

# The configuration part of the router script: its variable assignments, up to the point where it
# stops configuring and starts the server. Same extraction as run-agentic-kb-worker.sh, so the
# documentation is indexed under exactly the policy the router reads.
CONFIG=$(awk '
    /^[[:space:]]*(function[[:space:]]|[a-z-]*llm-router[[:space:]])/ { exit }
    /^[[:space:]]*(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*=/ { print }
' "$ROUTER_SCRIPT")
# shellcheck disable=SC2086
set -a; eval "$CONFIG"; set +a

# Publishing needs Redis only — the engine is reached later, by the worker — so this command
# neither logs in there nor imports sse_lib.

OPTIONS=()
SCOPE=""
DIRECTORIES=()
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run)   OPTIONS+=(--dry-run); shift ;;
        --force)     OPTIONS+=(--force); shift ;;
        --no-prune)  OPTIONS+=(--no-prune); shift ;;
        --config)    OPTIONS+=(--config "${2:?--config needs a path}"); shift 2 ;;
        --log-level) OPTIONS+=(--log-level "${2:?--log-level needs a level}"); shift 2 ;;
        --scope)     SCOPE="${2:?--scope needs a scope name}"; shift 2 ;;
        --)          shift; while [ $# -gt 0 ]; do DIRECTORIES+=("$1"); shift; done ;;
        -*)          echo "unknown option: $1" >&2; exit 2 ;;
        *)           DIRECTORIES+=("$1"); shift ;;
    esac
done

if [ "${#DIRECTORIES[@]}" -eq 0 ]; then
    echo "usage: $(basename "$0") [options] DIRECTORY [DIRECTORY...]" >&2
    exit 2
fi
if [ -n "$SCOPE" ] && [ "${#DIRECTORIES[@]}" -gt 1 ]; then
    echo "--scope names one collection and was given ${#DIRECTORIES[@]} directories" >&2
    exit 2
fi

KB_DOCS=${KB_DOCS:-llm-router-agentic-kb-docs}

if ! command -v "$KB_DOCS" >/dev/null 2>&1; then
    echo "docs command not found: $KB_DOCS" >&2
    echo "install it with: pip install \"radlab-llm-router-plugins[agentic-knowledge]\"" >&2
    exit 1
fi

status=0
for directory in "${DIRECTORIES[@]}"; do
    ARGS=(--path "$directory")
    if [ -n "$SCOPE" ]; then
        ARGS+=(--scope "$SCOPE")
    fi
    if [ "${#OPTIONS[@]}" -gt 0 ]; then
        ARGS+=("${OPTIONS[@]}")
    fi
    "$KB_DOCS" "${ARGS[@]}" || status=1
done
exit $status
