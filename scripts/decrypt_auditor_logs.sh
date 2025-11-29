#!/usr/bin/env bash
set -euo pipefail

AUDIT_DIR="logs/auditor"

for enc_file in "$AUDIT_DIR"/*.audit; do
    json_file="${enc_file%.audit}.json"

    echo "Decrypting $enc_file → $json_file"
    gpg --output "$json_file" --decrypt "$enc_file"
done