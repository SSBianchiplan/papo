#!/usr/bin/env bash
# Restauração a partir de uma pasta do backup.sh. DESTRUTIVO: substitui bancos e arquivos atuais.
# Uso: ./ops/restore.sh ./backups/20261002T021500Z
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?informe a pasta do backup}"
( cd "$SRC" && sha256sum -c SHA256SUMS ) || { echo "Backup corrompido: SHA256SUMS não confere."; exit 1; }
read -r -p "Isto apaga os dados atuais e restaura $SRC. Digite RESTAURAR para continuar: " ok
[ "$ok" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }
START=$(date +%s)
docker compose stop api worker web keycloak
for db in papo keycloak; do
  docker compose exec -T postgres pg_restore -U postgres --clean --if-exists --no-owner --role="$( [ "$db" = papo ] && echo papo_owner || echo keycloak )" -d "$db" < "$SRC/$db.dump"
done
# o dump carrega GRANTs, políticas de RLS e triggers: as invariantes voltam junto com os dados
docker compose exec -T minio sh -c 'rm -rf /data/* && tar -C /data -xf -' < "$SRC/minio.tar"
docker compose up -d
echo "Restaurado em $(( $(date +%s) - START ))s. Registre esse tempo no runbook."
