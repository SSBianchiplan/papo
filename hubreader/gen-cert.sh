#!/usr/bin/env bash
# Certificado próprio com o IP desta VPS no SAN. O Papo fixa este certificado (não confia em outro).
set -euo pipefail
IP="${1:?uso: ./gen-cert.sh <IP público>}"
mkdir -p tls
openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -subj "/CN=papo-hubreader" \
  -addext "subjectAltName=IP:${IP}" -keyout tls/key.pem -out tls/cert.pem 2>/dev/null
chown 10010:10010 tls/key.pem tls/cert.pem && chmod 600 tls/key.pem && chmod 644 tls/cert.pem
echo "Certificado gerado. Cole o conteúdo de tls/cert.pem no Papo (Docs do hub → fonte remota)."
