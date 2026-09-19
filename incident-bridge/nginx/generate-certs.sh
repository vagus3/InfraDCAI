#!/bin/sh
# Self-signed cert so nginx can terminate TLS locally. Browsers will warn --
# expected. Production uses a real Let's Encrypt cert, issued automatically.
set -e
cd "$(dirname "$0")"
mkdir -p certs

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/privkey.pem \
  -out certs/fullchain.pem \
  -subj "/CN=localhost"

echo "Wrote nginx/certs/{fullchain,privkey}.pem"
