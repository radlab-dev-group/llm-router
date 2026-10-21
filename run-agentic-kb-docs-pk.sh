#!/usr/bin/env bash
set -euo pipefail

# Personal variant of run-agentic-kb-docs.sh: pulls the environment from the personal router script
# (run-rest-api-gunicorn-pk.sh) rather than the shared one. What is scanned, published and pruned
# is the same.
#
#   bash run-agentic-kb-docs-pk.sh [options] DIRECTORY [DIRECTORY...]

exec bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run-agentic-kb-docs.sh" \
    "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run-rest-api-gunicorn-pk.sh" \
    "$@"
