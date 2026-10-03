#!/usr/bin/env bash
# Выкатка данных с рабочей машины на сервер.
#
#   SERVER=deploy@graham.example.ru ./deploy/push-data.sh
#
# Отчёты разбираются и проверяются локально; на сервер едет готовая база.
# Учётные записи посетителей живут только на сервере, поэтому таблицы входа
# (users, user_sessions, auth_tokens) не выгружаются и на сервере не
# трогаются: переносятся только данные.
#
# Перед заменой на сервере делается бэкап (deploy/backup.sh). Схема должна
# совпадать: сначала выкатите код (git pull + up -d --build), потом данные.
set -euo pipefail

: "${SERVER:?Укажите SERVER=user@host}"
REMOTE_DIR="${REMOTE_DIR:-/opt/graham}"
LOCAL_CONTAINER="${POSTGRES_CONTAINER:-graham_postgres}"
LOCAL_USER="${POSTGRES_USER:-graham_user}"
LOCAL_DB="${POSTGRES_DB:-graham_analyzer}"
# Вместе со счётчиками id: иначе pg_restore --clean попробует удалить
# последовательность, на которой держится таблица на сервере.
AUTH_TABLES=(users user_sessions auth_tokens)

EXCLUDE=()
for t in "${AUTH_TABLES[@]}"; do EXCLUDE+=(-T "$t" -T "${t}_id_seq"); done

TMP="$(mktemp -t graham-data-XXXXXX.dump)"
trap 'rm -f "$TMP"' EXIT

echo "Выгрузка локальной базы без таблиц входа…"
docker exec "$LOCAL_CONTAINER" pg_dump -U "$LOCAL_USER" -Fc --no-owner --no-acl "${EXCLUDE[@]}" "$LOCAL_DB" > "$TMP"
echo "Готово: $(du -h "$TMP" | cut -f1)"

scp -q "$TMP" "$SERVER:/tmp/graham-data.dump"

# shellcheck disable=SC2087
ssh "$SERVER" bash -s <<REMOTE
set -euo pipefail
cd "$REMOTE_DIR/deploy"
./backup.sh
set -a; source .env.prod; set +a
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.prod)
# --clean пересоздаёт только таблицы из файла: таблиц входа в нём нет.
"\${COMPOSE[@]}" exec -T db pg_restore -U "\$POSTGRES_USER" -d "\$POSTGRES_DB" --clean --if-exists --no-owner --no-acl --single-transaction < /tmp/graham-data.dump
rm -f /tmp/graham-data.dump
# Кэш расчётов увидит новые данные по статистике Postgres; перезапуск — для
# верности и чтобы прогрев начался сразу.
"\${COMPOSE[@]}" restart backend
echo "Данные на сервере обновлены."
REMOTE
