#!/usr/bin/env bash
# Очищенная копия репозитория для переезда на новый GitHub.
#
# Исходный репозиторий не трогается: скрипт клонирует его в отдельную папку и
# переписывает историю там. Из всех коммитов всех веток убираются:
#
#   1. .env — локальные настройки с токеном T-Invest;
#   2. токены вида «t.…» (T-Invest) и ключи Alibaba (LTAI…) в любых файлах —
#      заменяются заглушкой (старый токен попадал и в env.example);
#   3. все дампы базы (*.dump, каталог backups/postgres/). Раньше убирались
#      только дампы с данными аккаунтов; с 24.10.2026 — все: в них вся
#      собранная и проверенная отчётность, и раздавать её архивом незачем.
#      Бэкапы живут на сервере (~/graham-backups) и локально, не в git;
#   4. документация, планы, гайды и материалы к конференции (PRIVATE_PATHS) —
#      они живут только локально и перечислены в .gitignore;
#   5. подписи соавторов-ассистентов в сообщениях коммитов («Co-Authored-By:
#      Claude…», «Generated with Claude Code») — по ним GitHub записывает в
#      контрибьюторы.
#
# Автор всех коммитов приводится к AUTHOR_EMAIL (скрытый адрес GitHub): в
# старых коммитах адрес записан с опечаткой, и GitHub не привязывал их к
# профилю.
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
# Нужен git filter-repo (apt install git-filter-repo или pipx install
# git-filter-repo).
set -euo pipefail

SRC="$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)"
DEST="${1:-$(dirname "$SRC")/graham-analyzer-clean}"
AUTHOR_NAME="${AUTHOR_NAME:-gosgosling}"
AUTHOR_EMAIL="${AUTHOR_EMAIL:-198343943+gosgosling@users.noreply.github.com}"
PRIVATE_PATHS=(docs/ plans/ "ROADMAP GA.md" conference-2026/ .claude/ .cursor/rules/)

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

# ── Дампы базы ───────────────────────────────────────────────────────────────
dumps=$(git -C "$SRC" rev-list --all --objects | awk '$2 ~ /\.dump$/' | sort -k2 -u | wc -l)
echo "Дампов в истории: $dumps — все будут удалены"
: > "$WORK/paths.txt"
printf '%s\n' "backups/postgres/" "glob:*.dump" >> "$WORK/paths.txt"

printf '%s\n' ".env" "${PRIVATE_PATHS[@]}" >> "$WORK/paths.txt"

# Все авторы и коммитеры истории — один человек под одним адресом.
git -C "$SRC" log --all --format='%an <%ae>%n%cn <%ce>' | sort -u \
  | sed "s|^|$AUTHOR_NAME <$AUTHOR_EMAIL> |" > "$WORK/mailmap.txt"

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
  --replace-text "$WORK/replace.txt" \
  --mailmap "$WORK/mailmap.txt" \
  --message-callback '
import re
message = re.sub(rb"(?im)^[ \t]*(co-authored-by:[^\n]*(claude|anthropic)[^\n]*|[^\n]*generated with \[?claude code[^\n]*)\n?", b"", message)
return message.rstrip() + b"\n"
'

git -C "$DEST" reflog expire --expire=now --all
git -C "$DEST" gc --quiet --prune=now --aggressive

echo
echo "Готово: $DEST"
git -C "$DEST" branch
du -sh "$SRC/.git" "$DEST/.git"
echo "Проверьте копию: scripts/check_secrets.py $DEST — и только потом пушьте."
