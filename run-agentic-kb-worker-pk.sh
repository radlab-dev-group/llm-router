#!/usr/bin/env bash
set -euo pipefail

# Personal variant of run-agentic-kb-worker.sh: pulls the environment from the
# personal router script (run-rest-api-gunicorn-pk.sh) rather than the shared
# one.  What the worker does and which options it takes is the same.
#
#   bash run-agentic-kb-worker-pk.sh [worker options...]

exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run-agentic-kb-worker.sh" \
    "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run-rest-api-gunicorn-pk.sh" \
    "$@"
