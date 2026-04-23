#!/usr/bin/env bash
#
# [INF-02] Backup automatizado do Postgres — pg_dump + upload para S3/B2.
#
# Uso em producao (cron diario):
#   0 3 * * * /opt/ia/scripts/pg_backup.sh >> /var/log/ia_backup.log 2>&1
#
# Variaveis de ambiente requeridas:
#   DATABASE_URL          (postgres://user:pass@host:5432/dbname)
#   BACKUP_S3_BUCKET      (ex: fluxo-ia-backups)
#   BACKUP_S3_PREFIX      (ex: postgres/prod)  — opcional
#   BACKUP_RETENTION_DAYS (default: 30)
#
# Ferramentas requeridas: pg_dump, aws cli (ou rclone), gzip
#
set -euo pipefail

# Carrega env se existir
if [ -f /etc/ia/backup.env ]; then
  # shellcheck disable=SC1091
  source /etc/ia/backup.env
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "ERRO: DATABASE_URL nao definido" >&2
  exit 1
fi
if [ -z "${BACKUP_S3_BUCKET:-}" ]; then
  echo "ERRO: BACKUP_S3_BUCKET nao definido" >&2
  exit 1
fi

PREFIX="${BACKUP_S3_PREFIX:-postgres/prod}"
RETENTION="${BACKUP_RETENTION_DAYS:-30}"
TS="$(date -u +%Y%m%d-%H%M%S)"
TMP="/tmp/ia-backup-${TS}.sql.gz"
REMOTE_PATH="s3://${BACKUP_S3_BUCKET}/${PREFIX}/ia-${TS}.sql.gz"

echo "[backup] ${TS} — iniciando pg_dump"
pg_dump --no-owner --no-privileges --format=plain --clean --if-exists \
  "${DATABASE_URL}" | gzip -9 > "${TMP}"

SIZE=$(stat -c%s "${TMP}" 2>/dev/null || stat -f%z "${TMP}")
echo "[backup] dump finalizado: ${SIZE} bytes"

if [ "${SIZE}" -lt 10240 ]; then
  echo "ERRO: backup suspeito muito pequeno (< 10KB). Abortando." >&2
  rm -f "${TMP}"
  exit 2
fi

echo "[backup] subindo para ${REMOTE_PATH}..."
aws s3 cp "${TMP}" "${REMOTE_PATH}" \
  --storage-class STANDARD_IA \
  --only-show-errors

rm -f "${TMP}"

echo "[backup] removendo backups mais antigos que ${RETENTION} dias..."
CUTOFF=$(date -u -d "-${RETENTION} days" +%Y%m%d 2>/dev/null || date -u -v-${RETENTION}d +%Y%m%d)
aws s3 ls "s3://${BACKUP_S3_BUCKET}/${PREFIX}/" | awk '{print $4}' | while read -r f; do
  FDATE=$(echo "$f" | sed -E 's/^ia-([0-9]{8}).*/\1/')
  if [ -n "${FDATE}" ] && [ "${FDATE}" \< "${CUTOFF}" ]; then
    aws s3 rm "s3://${BACKUP_S3_BUCKET}/${PREFIX}/${f}"
    echo "[backup] removido ${f}"
  fi
done

echo "[backup] concluido em $(date -u +%Y-%m-%dT%H:%M:%SZ)"
