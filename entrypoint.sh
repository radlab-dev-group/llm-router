#!/usr/bin/env bash
set -e

# Default values
DEBUG_MODE=false

for arg in "$@"; do
    case "$arg" in
        --debug|debug|--shell|shell)
            DEBUG_MODE=true
            ;;
    esac
done

echo "[entrypoint] Working directory: $(pwd)"

if [ "$DEBUG_MODE" = true ]; then
    echo "[entrypoint] Debug mode activated. Container will stay alive for exec."
    sleep infinity
    exit 0
fi

echo "[entrypoint] Starting application..."
exec python3 -m llm_router_api.rest_api
