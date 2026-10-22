#!/usr/bin/env bash
# Backup consistente: dump dos dois bancos + cópia dos arquivos do MinIO. Retenção configurável.
# Uso: ./ops/backup.sh [/destino]     Agende no cron do host, ex.: 15 2 * * * /opt/papo/ops/backup.sh /backups
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="${1:-./backups}"; KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"; OUT="$DEST/$STAMP"
mkdir -p "$OUT"
echo "[1/3] PostgreSQL → $OUT"
for db in papo keycloak; do
  docker compose exec -T postgres pg_dump -U postgres -Fc -d "$db" > "$OUT/$db.dump"
done
echo "[2/3] MinIO → $OUT/minio.tar"
docker compose exec -T minio sh -c 'tar -C /data -cf - .' > "$OUT/minio.tar"
echo "[3/3] Integridade"
( cd "$OUT" && sha256sum *.dump minio.tar > SHA256SUMS )
du -sh "$OUT"
find "$DEST" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" -print -exec rm -rf {} +
echo "OK: $OUT"
