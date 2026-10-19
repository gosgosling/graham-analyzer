#!/usr/bin/env bash
# Логический бэкап PostgreSQL из контейнера в файл на хосте (формат custom — сжатие, удобный pg_restore).
#
# Использование:
#   ./scripts/pg_backup.sh
#   POSTGRES_BACKUP_DIR=/mnt/shared/pg-backups ./scripts/pg_backup.sh
#
# Если «docker» без sudo не видит демон, скрипт сам попробует «sudo docker»
# (запросит пароль при первом вызове). Либо: sudo usermod -aG docker "$USER" && newgrp docker
# Принудительно только sudo: PG_DOCKER_FORCE_SUDO=1 ./scripts/pg_backup.sh
#
# Типичный запуск «перед поднятием приложения»:
#   docker compose up -d postgres
#   # дождаться healthy (или sleep 3)
#   ./scripts/pg_backup.sh
#   docker compose up -d
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/pg_docker.sh"
pg_docker_init || exit 1

CONTAINER="${POSTGRES_CONTAINER:-graham_postgres}"
PG_USER="${POSTGRES_USER:-graham_user}"
PG_DB="${POSTGRES_DB:-graham_analyzer}"
# Папка на хосте (расшарьте её в SMB/NFS и укажите путь здесь или через env)
BACKUP_ROOT="${POSTGRES_BACKUP_DIR:-$SCRIPT_DIR/../backups/postgres}"

if ! pg_docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Контейнер $CONTAINER не найден. Сначала: docker compose up -d postgres" >&2
  exit 1
fi

mkdir -p "$BACKUP_ROOT"
STAMP="$(date +%Y%m%d_%H%M%S)"
FILE="$BACKUP_ROOT/${PG_DB}_${STAMP}.dump"

# Аккаунты (email, хэши паролей, сессии) в основной дамп не кладутся: папка
# бэкапов коммитится в публичный репозиторий. Схема этих таблиц в дампе есть,
# данных нет. Сами данные — отдельным маленьким дампом в backups/private/,
# который в гит не попадает (.gitignore) и читается только владельцем.
AUTH_TABLES=(users user_sessions auth_tokens)
EXCLUDE=()
ONLY=()
for t in "${AUTH_TABLES[@]}"; do
  EXCLUDE+=(--exclude-table-data="public.$t")
  ONLY+=(-t "public.$t")
done
PRIVATE_ROOT="${POSTGRES_PRIVATE_BACKUP_DIR:-$BACKUP_ROOT/../private}"
mkdir -p "$PRIVATE_ROOT"
chmod 700 "$PRIVATE_ROOT"
AUTH_FILE="$PRIVATE_ROOT/${PG_DB}_auth_${STAMP}.dump"

echo "Бэкап $PG_DB → $FILE (без данных аккаунтов)"
pg_docker exec "$CONTAINER" pg_dump -U "$PG_USER" -Fc --no-owner --no-acl "${EXCLUDE[@]}" "$PG_DB" > "$FILE"

( umask 077 && pg_docker exec "$CONTAINER" pg_dump -U "$PG_USER" -Fc --no-owner --no-acl \
    --data-only "${ONLY[@]}" "$PG_DB" > "$AUTH_FILE" )

SIZE="$(du -h "$FILE" | cut -f1)"
echo "Готово ($SIZE). Аккаунты отдельно: $AUTH_FILE"
echo "Восстановление: ./scripts/pg_restore.sh \"$FILE\", затем при необходимости аккаунты:"
echo "  pg_restore --data-only из \"$AUTH_FILE\" (или заново: python -m scripts.create_admin)"

# Опционально: хранить только последние KEEP_BACKUPS файлов
if [[ -n "${POSTGRES_BACKUP_KEEP:-}" ]]; then
  KEEP="$POSTGRES_BACKUP_KEEP"
  ls -1t "$BACKUP_ROOT"/${PG_DB}_*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f --
  echo "Оставлены последние $KEEP бэкапов в $BACKUP_ROOT"
fi
