#!/usr/bin/env bash
# Отчёт о посещаемости по журналу веб-сервера — запускается на своей машине:
#
#   SERVER=ubuntu@185.149.147.111 ./deploy/traffic-report.sh
#
# Журнал Caddy лежит на сервере в /opt/graham/logs/caddy (за 30 дней, см.
# Caddyfile). Скрипт склеивает его там же, отбрасывает служебные запросы и
# собирает HTML-отчёт GoAccess в одноразовом контейнере; на свою машину
# приходит только готовый отчёт. IP в нём обезличены (--anonymize-ip):
# сам отчёт — не журнал, ему адреса посетителей ни к чему.
#
# Метрика и журнал считают разное и оба нужны. Метрика не видит тех, у кого
# её режет блокировщик, и поисковых роботов; журнал видит всех, но не знает,
# откуда человек пришёл, если браузер не передал адрес.
#
# Переменные:
#   OUT        — куда положить отчёт (по умолчанию ./traffic-YYYY-MM-DD.html)
#   CRAWLERS=1 — учитывать поисковых роботов (по умолчанию — только люди)
#   EXCLUDE_IP — свой IP через пробел, чтобы не считать свои заходы
set -euo pipefail

SERVER="${SERVER:?укажите SERVER=user@host}"
OUT="${OUT:-traffic-$(date +%F).html}"
REMOTE_DEPLOY="${REMOTE_DEPLOY:-/opt/graham/deploy}"
args=(--log-format=CADDY --anonymize-ip --tz=Europe/Moscow -o html)
[[ "${CRAWLERS:-0}" == 1 ]] || args+=(--ignore-crawlers)
for ip in ${EXCLUDE_IP:-}; do args+=("--exclude-ip=$ip"); done

# Служебное — не посещения: запросы страницы к API, файлы сборки, иконки.
# Иначе один просмотр карточки считался бы десятком «хитов».
#
# Файлы журнала Caddy пишет от root с правами 0600, поэтому читаем их через
# сам контейнер web, а не с диска сервера.
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.prod"

# Журнала ещё нет — до первой выкатки с записью в файл (deploy/Caddyfile)
# Caddy пишет только в вывод контейнера.
# shellcheck disable=SC2029
if ! ssh "$SERVER" "cd '$REMOTE_DEPLOY' && $COMPOSE exec -T web sh -c 'ls /var/log/caddy/access*.log' >/dev/null 2>&1"; then
  echo "На сервере нет журнала /var/log/caddy/access.log в контейнере web." >&2
  echo "Он появится после выкатки с deploy/Caddyfile, где журнал пишется в файл." >&2
  exit 1
fi

trap '[[ -s "$OUT" ]] || rm -f "$OUT"' EXIT
# shellcheck disable=SC2029
ssh "$SERVER" "set -o pipefail; cd '$REMOTE_DEPLOY' && \
  docker pull -q allinurl/goaccess:latest >/dev/null && \
  $COMPOSE exec -T web sh -c \
    'cd /var/log/caddy && for f in access*.log.gz; do [ -e \"\$f\" ] && zcat \"\$f\"; done; cat access*.log' \
  | grep -v -E '\"uri\":\"/(api/|static/|favicon|manifest\\.json|logo)' \
  | docker run --rm -i allinurl/goaccess:latest - ${args[*]} 2>/dev/null" > "$OUT" \
  || { echo "Не удалось собрать отчёт на сервере." >&2; exit 1; }

echo "Отчёт: $OUT ($(du -h "$OUT" | cut -f1))"
