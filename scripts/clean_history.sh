#!/usr/bin/env bash
# Очищенная копия репозитория для переезда на новый GitHub.
#
# Исходный репозиторий не трогается: скрипт клонирует его в отдельную папку и
# переписывает историю там. Из всех коммитов всех веток убираются:
#
#   1. .env — локальные настройки с токеном T-Invest;
#   2. токены вида «t.…» (T-Invest) и ключи Alibaba (LTAI…) в любых файлах —
#      заменяются заглушкой (старый токен попадал и в env.example);
#   3. дампы базы, в которых есть строки таблиц users / user_sessions /
#      auth_tokens (хэши паролей, e-mail, сессии). Дампы без данных аккаунтов
#      остаются — бэкапы в git нужны.
#
# В копию попадают только закоммиченные изменения. Перед переездом:
# закоммитить работу в исходном репозитории и запустить скрипт заново.
#
# Значения секретов скрипт не печатает: шаблоны лежат здесь, а сами токены
# находит git filter-repo.
#
# Запуск:
#   ./scripts/clean_history.sh [папка-назначения]
#   (по умолчанию ../graham-analyzer-clean рядом с репозиторием)
#
# Нужны: git filter-repo (apt install git-filter-repo или pipx install
# git-filter-repo) и запущенный контейнер Postgres (для pg_restore — проверка
# дампов). Имя контейнера — PG_CONTAINER, по умолчанию graham_postgres.
set -euo pipefail

SRC="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)"
DEST="${1:-$(dirname "$SRC")/graham-analyzer-clean}"
PG_CONTAINER="${PG_CONTAINER:-graham_postgres}"

source "$SRC/scripts/pg_docker.sh"
pg_docker_init

if ! git filter-repo --version >/dev/null 2>&1; then
  echo "Нет git filter-repo: apt install git-filter-repo (или pipx install git-filter-repo)" >&2
  exit 1
fi
if [[ -e "$DEST" ]]; then
  echo "Папка $DEST уже есть — удалите её или укажите другую" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
umask 077

# ── Дампы с данными аккаунтов ────────────────────────────────────────────────
echo "Проверка дампов в истории…"
: > "$WORK/paths.txt"
total=0
while read -r sha path; do
  total=$((total + 1))
  rows=$(git -C "$SRC" cat-file blob "$sha" \
    | pg_docker exec -i "$PG_CONTAINER" pg_restore -a -t users -t user_sessions -t auth_tokens -f - 2>/dev/null \
    | awk '/^COPY /{c=1;next} /^\\\.$/{c=0;next} c{n++} END{print n+0}' || true)
  # Не удалось прочитать дамп — считаем, что аккаунты в нём есть: лишний
  # удалённый бэкап лучше утёкших хэшей.
  if [[ -z "$rows" || "$rows" -gt 0 ]]; then
    printf '%s\n' "$path" >> "$WORK/paths.txt"
  fi
done < <(git -C "$SRC" rev-list --all --objects | awk '$2 ~ /\.dump$/' | sort -k2 -u)
echo "Дампов в истории: $total, с данными аккаунтов: $(wc -l < "$WORK/paths.txt")"

printf '%s\n' ".env" >> "$WORK/paths.txt"

cat > "$WORK/replace.txt" <<'EOF'
regex:\bt\.[A-Za-z0-9_-]{60,}==>REMOVED_TINVEST_TOKEN
regex:LTAI[A-Za-z0-9]{12,}==>REMOVED_ALIBABA_KEY
EOF

# ── Клон и перепись истории ──────────────────────────────────────────────────
echo "Клонирование в $DEST…"
git clone --quiet --no-local "$SRC" "$DEST"
# Все ветки исходного репозитория — локальными ветками копии.
for ref in $(git -C "$SRC" for-each-ref --format='%(refname:short)' refs/heads); do
  git -C "$DEST" show-ref --verify --quiet "refs/heads/$ref" \
    || git -C "$DEST" branch --quiet --track "$ref" "origin/$ref"
done

git -C "$DEST" filter-repo --force \
  --invert-paths --paths-from-file "$WORK/paths.txt" \
  --replace-text "$WORK/replace.txt"

git -C "$DEST" reflog expire --expire=now --all
git -C "$DEST" gc --quiet --prune=now --aggressive

echo
echo "Готово: $DEST"
git -C "$DEST" branch
du -sh "$SRC/.git" "$DEST/.git"
echo "Проверьте копию: scripts/check_secrets.py $DEST — и только потом пушьте."
