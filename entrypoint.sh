#!/usr/bin/env bash
set -e

# Default values
APP_SCRIPT="run-rest-api-gunicorn.sh"
DEBUG_MODE=false

for arg in "$@"; do
    case "$arg" in
        --debug|debug|--shell|shell)
            DEBUG_MODE=true
            ;;
        --runserver|runserver)
            APP_SCRIPT="run-rest-api.sh"
            ;;
    esac
done

echo "[entrypoint] Working directory: $(pwd)"

if [ "$DEBUG_MODE" = true ]; then
    echo "[entrypoint] Debug mode activated. Container will stay alive for exec."
    sleep infinity
    exit 0
fi

if [ ! -f "./$APP_SCRIPT" ]; then
    echo "[entrypoint] ERROR: Script $APP_SCRIPT not found!"
    exit 1
fi

echo "[entrypoint] Starting application using $APP_SCRIPT ..."
exec "./$APP_SCRIPT"
