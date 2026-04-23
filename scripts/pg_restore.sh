#!/usr/bin/env bash
#
# [INF-02] Restore de backup do Postgres — para teste mensal de disaster recovery.
#
# Uso:
#   scripts/pg_restore.sh s3://bucket/prefix/ia-20260420-030000.sql.gz target_database_url
#
# IMPORTANTE: este script e DESTRUTIVO no banco de destino.
# Use sempre contra um ambiente de teste/DR, nao em producao.
#
set -euo pipefail

BACKUP_URL="${1:-}"
TARGET_URL="${2:-}"

if [ -z "${BACKUP_URL}" ] || [ -z "${TARGET_URL}" ]; then
  echo "Uso: $0 <backup_s3_url> <target_database_url>" >&2
  echo "Ex:  $0 s3://fluxo-ia-backups/postgres/prod/ia-20260420-030000.sql.gz postgres://...restore-target" >&2
  exit 1
fi

TMP="/tmp/ia-restore-$$-$(date +%s).sql.gz"

echo "[restore] baixando ${BACKUP_URL}..."
aws s3 cp "${BACKUP_URL}" "${TMP}"

echo "[restore] restaurando em ${TARGET_URL%@*}@... (destrutivo)"
gunzip -c "${TMP}" | psql "${TARGET_URL}"

rm -f "${TMP}"
echo "[restore] concluido"
