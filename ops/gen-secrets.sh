#!/usr/bin/env bash
# Gera segredos aleatórios. Uso: ./ops/gen-secrets.sh >> .env   (rode uma vez só)
set -euo pipefail
gen() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "${1:-40}"; }
cat <<EOS
POSTGRES_PASSWORD=$(gen)
PAPO_OWNER_PASSWORD=$(gen)
PAPO_APP_PASSWORD=$(gen)
KEYCLOAK_DB_PASSWORD=$(gen)
KEYCLOAK_ADMIN_PASSWORD=$(gen 24)
REDIS_PASSWORD=$(gen)
MINIO_ROOT_USER=papo$(gen 8)
MINIO_ROOT_PASSWORD=$(gen)
SECRETS_KEY=$(gen 48)
HUBGW_TOKEN=$(gen 48)
EOS
