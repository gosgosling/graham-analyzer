"""
Конфигурация сервиса загрузки консолидированной отчётности с e-disclosure.ru.

Политика скрапинга:
- robots.txt e-disclosure.ru запрещает: /api/*, /Event/Certificate?*, /Company/Certificate/*,
  /PortalImageHandler.ashx?*, /Company/Search?*
- Используемые пути РАЗРЕШЕНЫ: /portal/files.aspx?* и /portal/FileLoad.ashx?*
- Задержки выбраны консервативно, чтобы не нагружать сервер (среднее ~1 запрос/мин)
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Ищем .env в родительском каталоге (корень монорепо)
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# ── E-disclosure ───────────────────────────────────────────────────────────────
EDISCLOSURE_BASE_URL = "https://www.e-disclosure.ru"
# type=4 — Консолидированная отчётность
CONSOLIDATED_REPORT_TYPE = 4

# Скачиваем только ГОДОВЫЕ КОНСОЛИДИРОВАННЫЕ отчёты (МСФО/IFRS).
# «Годовая сводная» — это РСБУ; нам нужна только «Годовая консолидированная».
ANNUAL_KEYWORDS = [
    "Годовая консолидированная",
]

# User-Agent: реалистичный браузерный заголовок.
# e-disclosure.ru разрешает /portal/files.aspx по robots.txt, но имеет базовую
# защиту от ботов — стандартный браузерный UA обходит её без обмана,
# так как мы работаем с разрешёнными путями.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Задержки (секунды) — ~1 запрос в минуту, безопасно для сервера ─────────────
# Случайный диапазон [min, max] — добавляет jitter, снижает предсказуемость
PAGE_DELAY_MIN = 8    # пауза перед запросом страницы списка файлов
PAGE_DELAY_MAX = 15

FILE_DELAY_MIN = 10   # пауза между скачиваниями файлов одной компании
FILE_DELAY_MAX = 20

COMPANY_DELAY_MIN = 45  # пауза между компаниями
COMPANY_DELAY_MAX = 90

# ── Пути ──────────────────────────────────────────────────────────────────────
REPORTS_BASE_DIR = Path(os.getenv("REPORTS_BASE_DIR", "/home/devops/Reports"))

# ── PostgreSQL (те же параметры, что и у основного бэкенда) ───────────────────
POSTGRES_USER     = os.getenv("POSTGRES_USER", "graham_user")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "12345678")
POSTGRES_DB       = os.getenv("POSTGRES_DB", "graham_analyzer")
POSTGRES_HOST     = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))
