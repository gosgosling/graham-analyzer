# Бэкенд: FastAPI + планировщик в одном процессе.
#
# Собирается из корня репозитория (контекст — `.`): бэкенд импортирует
# tools/edisclosure-scraper. Браузеры Playwright в образ не ставятся — сбор
# раскрытий и разбор PDF идут на рабочей машине, а на сервер приезжает
# готовая база (deploy/push-data.sh).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend/ backend/
COPY tools/edisclosure-scraper/ tools/edisclosure-scraper/

RUN useradd --system --uid 10001 --home-dir /app app \
    && chown -R app:app /app
USER app

WORKDIR /app/backend
EXPOSE 8000

# Миграции — при каждом старте: на пустой базе создадут схему, на свежей
# ничего не сделают. Воркер один: планировщик живёт в процессе приложения,
# и при двух воркерах ежедневное обновление цен шло бы дважды.
# --proxy-headers: реальный адрес посетителя берётся из X-Forwarded-For от
# Caddy — по нему считаются попытки входа. Снаружи бэкенд недоступен, так
# что доверять заголовку от любого соседа по сети можно.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
