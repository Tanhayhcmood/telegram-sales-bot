#!/bin/bash
set -e

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/telegram_agent_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "=== Backing up database at $TIMESTAMP ==="

PGPASSWORD="${POSTGRES_PASSWORD:-changeme}" pg_dump \
    -h "${POSTGRES_HOST:-localhost}" \
    -U "${POSTGRES_USER:-postgres}" \
    -d "${POSTGRES_DB:-telegram_agent}" \
    --no-password \
    | gzip > "$BACKUP_FILE"

echo "Backup saved to: $BACKUP_FILE"

find "$BACKUP_DIR" -name "*.sql.gz" -mtime +7 -delete
echo "Old backups cleaned up."
