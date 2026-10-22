#!/bin/bash
# Executado uma única vez, na criação do volume. Papéis separados: dono do schema (migrations) e aplicação.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE papo_owner LOGIN PASSWORD '${PAPO_OWNER_PASSWORD}';
CREATE ROLE papo_app   LOGIN PASSWORD '${PAPO_APP_PASSWORD}';
CREATE ROLE keycloak   LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
CREATE DATABASE papo OWNER papo_owner;
CREATE DATABASE keycloak OWNER keycloak;
REVOKE ALL ON DATABASE papo FROM PUBLIC;
GRANT CONNECT ON DATABASE papo TO papo_app;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname papo <<SQL
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO papo_app;
ALTER SCHEMA public OWNER TO papo_owner;
SQL
