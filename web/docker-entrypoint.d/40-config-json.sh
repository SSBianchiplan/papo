#!/bin/sh
# Configuração de runtime: a mesma imagem serve qualquer domínio.
set -eu
cat > /usr/share/nginx/html/config.json <<JSON
{"authMode":"oidc","authority":"${AUTH_URL:-https://${AUTH_DOMAIN}}/realms/${KC_REALM:-papo}","clientId":"${OIDC_CLIENT_ID:-papo-web}"}
JSON
