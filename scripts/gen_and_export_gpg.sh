#!/usr/bin/env bash
set -euo pipefail

# --------------------------------------------------------------
# 1️⃣  Settings – adjust them to your needs
# --------------------------------------------------------------
read -p "Enter email: " EMAIL
echo

read -s -p "Enter passphrase: " PASSPHRASE
echo

PUB_KEY_FILE="llm-router-auditor-pub.asc"
PRIV_KEY_FILE="llm-router-auditor-priv.asc"

# --------------------------------------------------------------
# 2️⃣  Generate the key in batch mode (no interaction)
# --------------------------------------------------------------
gpg --batch --generate-key <<EOF
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: LLM Router auditor key
Name-Comment: llm-router-auditor
Name-Email: $EMAIL
Expire-Date: 0
Passphrase: $PASSPHRASE
%commit
EOF

# --------------------------------------------------------------
# 3️⃣  Retrieve the fingerprint of the newly created key
# --------------------------------------------------------------
FPR=$(gpg --list-secret-keys --with-colons "$EMAIL" \
       | awk -F: '/^sec/ {print $5; exit}')
echo "Created key with fingerprint: $FPR"

# --------------------------------------------------------------
# 4️⃣  Export public and private keys to the specified files
# --------------------------------------------------------------
gpg --armor --output "$PUB_KEY_FILE"  --export "$FPR"
gpg --armor --output "$PRIV_KEY_FILE" --export-secret-keys "$FPR"

echo "✅ Public key saved to: $PUB_KEY_FILE"
echo "✅ Private key saved to: $PRIV_KEY_FILE"