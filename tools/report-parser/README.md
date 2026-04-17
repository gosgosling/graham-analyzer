# CLI AI-парсера финансовых отчётов

CLI-обёртка поверх сервиса `backend/app/services/report_parser/`. Она обходит
папку `/home/devops/Reports/{TICKER}/{YEAR}_annual_consolidated/*.pdf`,
находит для каждого тикера компанию в БД и запускает LLM-пайплайн парсинга.

## Быстрый старт

CLI переиспользует пакет `app.*` из backend, поэтому запускать её нужно
из backend-виртуального окружения (там уже установлены pymupdf, openai,
sqlalchemy и т.д.):

```bash
cd /home/devops/projects/git_clone/graham-analyzer/backend
source venv/bin/activate

# LLM-ключ берётся из корневого .env проекта (LLM_API_KEY, LLM_MODEL, ...)
# См. backend/app/config.py и корневой .env.

cd ../tools/report-parser
# Пробный прогон на одном отчёте, без записи в БД
python main.py --ticker LKOH --year 2023 --dry-run

# Реально создать черновик отчёта в БД
python main.py --ticker LKOH --year 2023

# Прогнать все распакованные PDF во всей папке Reports/
python main.py
```

Все созданные отчёты помечаются как:
- `auto_extracted = True`
- `verified_by_analyst = False`
- `extraction_notes` содержит служебную шапку + заметки LLM +
  автоматические флаги для проверки,
- `extraction_model` = `{LLM_PROVIDER}:{LLM_MODEL}`,
- `source_pdf_path` = полный путь к PDF.

Чтобы подтвердить отчёт после ручной проверки — используй веб-форму
(обычное сохранение через форму выставит `verified_by_analyst=True`) или
напрямую `POST /reports/{id}/verify`.

## Ключи CLI

```
python main.py [--ticker TICKER] [--year YEAR] [--pdf PATH]
               [--reports-dir DIR] [--dry-run] [--force]
               [--log-level LEVEL]
```

- `--ticker` — обработать только указанный тикер.
- `--year` — ограничить годом.
- `--pdf` — обработать конкретный PDF (требует `--ticker` и `--year`).
- `--reports-dir` — корневой путь к отчётам (по умолчанию `/home/devops/Reports`).
- `--dry-run` — прогнать извлечение, но НЕ писать в БД.
- `--force` — пересоздать отчёт, если он уже есть в БД.
- `--log-level` — `DEBUG|INFO|WARNING|ERROR`.

## Настройки LLM

Все LLM-настройки читаются из `backend/app/config.py → settings.LLM_*`.
Источник — корневой `.env` проекта. Для переопределения только в CLI можно
завести `tools/report-parser/.env` (он имеет приоритет).

Поддерживаются три провайдера через один OpenAI-совместимый API:

### OpenAI
```
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

### Ollama (локально)
```
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:7b
```

### OpenRouter
```
LLM_PROVIDER=openrouter
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-...
LLM_MODEL=anthropic/claude-3.5-haiku
```

## Как работает «умный выбор страниц»

Финансовые отчёты бывают 100-300 страниц; скармливать весь PDF в LLM дорого
и нестабильно. Поэтому `pdf_extractor.py`:

1. Извлекает полный текст PDF постранично (PyMuPDF).
2. Ищет страницы-кандидаты по ключевым фразам («Консолидированный баланс»,
   «Отчёт о финансовом положении», «Отчёт о прибылях и убытках»,
   «Чистые процентные доходы» и т.п.).
3. Берёт каждую такую страницу плюс 1 соседнюю (таблицы часто ломаются
   через страницу).
4. Передаёт в LLM только собранный фрагмент текста.

На отчёте ЛУКОЙЛа за 2023 г. (41 страница) в контекст LLM попадает
~18 страниц / ~50 КБ текста.
