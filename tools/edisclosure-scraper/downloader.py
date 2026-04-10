"""
Загрузка файлов с e-disclosure.ru в локальные папки.

Файлы скачиваются через requests с cookies, полученными от Playwright
(они уже содержат ServicePipe-токен после прохождения JS-челленджа).
Для простоты и скорости cookies кешируются в рамках одного запуска.

Структура хранения:
  /home/devops/Reports/
    ROSN/
      2024_annual_consolidated.zip
      2023_annual_consolidated.zip
      ...
    SBER/
      2025_annual_consolidated.zip
      ...

Уже скачанные файлы пропускаются (idempotent).
"""

import logging
import time
import random
from pathlib import Path

import requests

from config import FILE_DELAY_MIN, FILE_DELAY_MAX, REPORTS_BASE_DIR, USER_AGENT
from scraper import ReportEntry

logger = logging.getLogger(__name__)

# Кеш cookies ServicePipe для текущего запуска (обновляется при первом использовании)
_sp_cookies: dict[str, str] = {}


def _get_sp_cookies() -> dict[str, str]:
    """
    Получает cookies ServicePipe через Playwright (если ещё не получены).
    Cookies действительны на протяжении сессии (~30 мин).
    """
    global _sp_cookies
    if _sp_cookies:
        return _sp_cookies

    from playwright.sync_api import sync_playwright

    logger.info("Получаем ServicePipe-cookies через Playwright...")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )
            page = context.new_page()
            # Открываем главную — это самый лёгкий способ получить SP cookies
            page.goto("https://www.e-disclosure.ru/", wait_until="networkidle", timeout=45_000)
            pw_cookies = context.cookies()
            browser.close()

        _sp_cookies = {c["name"]: c["value"] for c in pw_cookies}
        logger.info("Получено %d cookies.", len(_sp_cookies))
    except Exception as exc:
        logger.warning("Не удалось получить SP cookies: %s. Пробуем без cookies.", exc)
        _sp_cookies = {}

    return _sp_cookies


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/octet-stream,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9",
        "Referer": "https://www.e-disclosure.ru/",
    })
    cookies = _get_sp_cookies()
    session.cookies.update(cookies)
    return session


def _ticker_dir(ticker: str) -> Path:
    d = REPORTS_BASE_DIR / ticker.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _filename_for(report: ReportEntry) -> str:
    ext = "zip"
    label_lower = report.file_label.lower()
    for candidate in ("pdf", "zip", "rar", "docx", "doc", "xlsx"):
        if candidate in label_lower:
            ext = candidate
            break
    return f"{report.year}_annual_consolidated.{ext}"


def download_reports(ticker: str, reports: list[ReportEntry]) -> dict[str, str]:
    """
    Скачивает список отчётов для данного тикера.
    Возвращает словарь {год: путь_к_файлу} для успешно скачанных/уже имеющихся.
    """
    if not reports:
        return {}

    ticker_dir = _ticker_dir(ticker)
    session = _make_session()
    result: dict[str, str] = {}

    for report in sorted(reports, key=lambda r: r.year, reverse=True):
        filename = _filename_for(report)
        dest = ticker_dir / filename

        if dest.exists():
            logger.info("[%s] Файл %s уже существует — пропускаем.", ticker, filename)
            result[str(report.year)] = str(dest)
            continue

        delay = random.uniform(FILE_DELAY_MIN, FILE_DELAY_MAX)
        logger.debug("[%s] Ждём %.1f с перед скачиванием %s...", ticker, delay, filename)
        time.sleep(delay)

        logger.info("[%s] Скачиваем %s → %s", ticker, report.file_url, filename)
        try:
            resp = session.get(report.file_url, timeout=120, stream=True)
            resp.raise_for_status()

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            size_kb = dest.stat().st_size / 1024
            logger.info("[%s] ✓ Сохранён %s (%.0f КБ)", ticker, filename, size_kb)
            result[str(report.year)] = str(dest)

        except requests.HTTPError as exc:
            logger.error("[%s] HTTP-ошибка %s: %s", ticker, report.file_url, exc)
        except requests.RequestException as exc:
            logger.error("[%s] Ошибка сети %s: %s", ticker, report.file_url, exc)
        except OSError as exc:
            logger.error("[%s] Ошибка записи %s: %s", ticker, dest, exc)

    return result
