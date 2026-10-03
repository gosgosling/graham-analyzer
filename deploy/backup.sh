#!/usr/bin/env bash
# Ежедневный бэкап боевой базы. Запускается на сервере из cron:
#
#   15 4 * * *  /opt/graham/deploy/backup.sh >> /var/log/graham-backup.log 2>&1
#
# Кладёт pg_dump (формат custom, сжатый) в BACKUP_DIR и держит последние
# KEEP файлов. Копия на том же диске от потери сервера не спасает — укажите
# BACKUP_REMOTE (любой адрес для rsync: user@host:/path или смонтированная
# папка), и свежий файл уедет туда же.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
BACKUP_DIR="${BACKUP_DIR:-$HOME/graham-backups}"
KEEP="${KEEP:-14}"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

# shellcheck disable=SC1091
set -a; source .env.prod; set +a

mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/${POSTGRES_DB}_$(date +%Y%m%d_%H%M%S).dump"
"${COMPOSE[@]}" exec -T db pg_dump -U "$POSTGRES_USER" -Fc --no-owner --no-acl "$POSTGRES_DB" > "$FILE"
echo "$(date -Is) бэкап: $FILE ($(du -h "$FILE" | cut -f1))"

ls -1t "$BACKUP_DIR"/"${POSTGRES_DB}"_*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm -f --

if [[ -n "${BACKUP_REMOTE:-}" ]]; then
  rsync -a "$FILE" "$BACKUP_REMOTE"/
  echo "$(date -Is) копия: $BACKUP_REMOTE"
fi
