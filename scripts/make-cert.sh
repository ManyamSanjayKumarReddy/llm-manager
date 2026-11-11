#!/usr/bin/env bash
# Create a self-signed certificate in ./certs (browsers will warn once; for a real one, put
# your own fullchain.pem and privkey.pem there instead).
# Usage: scripts/make-cert.sh [hostname-or-ip ...]   (default: localhost 127.0.0.1)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs
names=("${@:-localhost}")
[[ $# -eq 0 ]] && names=(localhost 127.0.0.1)
san=""
for n in "${names[@]}"; do
  if [[ "$n" =~ ^[0-9.]+$ || "$n" == *:* ]]; then san+="IP:$n,"; else san+="DNS:$n,"; fi
done
openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
  -keyout certs/privkey.pem -out certs/fullchain.pem \
  -subj "/CN=${names[0]}" -addext "subjectAltName=${san%,}" 2>/dev/null
# keep the key readable only by the account that runs the backend
chmod 700 certs
chmod 600 certs/privkey.pem; chmod 644 certs/fullchain.pem
echo "certificate written to certs/ (valid for: ${names[*]})"
