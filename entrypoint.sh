#!/bin/bash
set -e

if [ "$1" = "SLEEP" ]; then
  echo "[Entrypoint] Debug mode: sleeping indefinitely..."
  sleep infinity
fi

echo "[Entrypoint] Creating supervisord.conf ..."
envsubst < docker/supervisord.conf.template > /etc/supervisor/conf.d/supervisord.conf

echo "[Entrypoint] Starting supervisord..."
supervisord