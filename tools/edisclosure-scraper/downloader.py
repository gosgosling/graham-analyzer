"""
Загрузка файлов с e-disclosure.ru и сохранение годового отчёта как PDF.

Итоговая структура:
  /home/devops/Reports/TATN/
    TATN_2024.pdf
    TATN_2023.pdf
    ...

Архивы zip после успешного извлечения PDF удаляются.
Если с сервера приходит уже PDF — сохраняется как TICKER_YEAR.pdf.
"""

import logging
import random
import shutil
import time
from pathlib import Path

import requests

from config import FILE_DELAY_MIN, FILE_DELAY_MAX, REPORTS_BASE_DIR, USER_AGENT
from pdf_extract import extract_main_pdf_from_zip, pdf_exists, pdf_target_path, process_orphan_zips_in_ticker_dir
from scraper import ReportEntry

logger = logging.getLogger(__name__)

_sp_cookies: dict[str, str] = {}


def _get_sp_cookies() -> dict[str, str]:
    global _sp_cookies
    if _sp_cookies:
        return _sp_cookies

    from playwright.sync_api import sync_playwright

    logger.info("Получаем ServicePipe-cookies через Playwright...")
    try:
        with sync_playwright() as pw:
            launch_kw = {
                "headless": True,
                "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            }
            ep = pw.chromium.executable_path
            if ep:
                launch_kw["executable_path"] = ep
            browser = pw.chromium.launch(**launch_kw)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )
            page = context.new_page()
            page.goto("https://www.e-disclosure.ru/", wait_until="domcontentloaded", timeout=60_000)
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
    session.cookies.update(_get_sp_cookies())
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


def _download_to_path(session: requests.Session, url: str, dest: Path) -> None:
    resp = session.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)


def download_reports(ticker: str, reports: list[ReportEntry]) -> dict[str, str]:
    """
    Скачивает отчёты и сохраняет как TICKER_YEAR.pdf.
    Возвращает словарь {год: путь_к_pdf}.
    """
    if not reports:
        return {}

    ticker_dir = _ticker_dir(ticker)
    # Обработать ранее скачанные zip без PDF (повторный запуск)
    process_orphan_zips_in_ticker_dir(ticker, ticker_dir)

    session = _make_session()
    result: dict[str, str] = {}

    for report in sorted(reports, key=lambda r: r.year, reverse=True):
        year = report.year
        pdf_path = pdf_target_path(ticker, year, ticker_dir)

        if pdf_path.exists():
            logger.info("[%s] PDF за %s уже есть — %s", ticker, year, pdf_path.name)
            result[str(year)] = str(pdf_path)
            continue

        filename = _filename_for(report)
        dest = ticker_dir / filename

        # Старый запуск: остался только zip — распаковать без повторной загрузки
        if dest.exists() and dest.suffix.lower() == ".zip":
            extracted = extract_main_pdf_from_zip(dest, ticker, year, ticker_dir, delete_zip=True)
            if extracted:
                result[str(year)] = str(extracted)
            continue

        if dest.exists() and dest.suffix.lower() == ".pdf":
            shutil.copy2(dest, pdf_path)
            # если имя не совпадало — оставляем только целевое имя
            if dest != pdf_path:
                dest.unlink(missing_ok=True)
            logger.info("[%s] ✓ Сохранён %s", ticker, pdf_path.name)
            result[str(year)] = str(pdf_path)
            continue

        delay = random.uniform(FILE_DELAY_MIN, FILE_DELAY_MAX)
        logger.debug("[%s] Ждём %.1f с перед скачиванием %s...", ticker, delay, filename)
        time.sleep(delay)

        logger.info("[%s] Скачиваем %s → %s", ticker, report.file_url, filename)
        try:
            _download_to_path(session, report.file_url, dest)
            size_kb = dest.stat().st_size / 1024
            logger.info("[%s] ✓ Сохранён временный файл %s (%.0f КБ)", ticker, filename, size_kb)

            suffix = dest.suffix.lower()
            if suffix == ".pdf":
                shutil.copy2(dest, pdf_path)
                dest.unlink(missing_ok=True)
                logger.info("[%s] ✓ Сохранён %s", ticker, pdf_path.name)
                result[str(year)] = str(pdf_path)
            elif suffix == ".zip":
                extracted = extract_main_pdf_from_zip(dest, ticker, year, ticker_dir, delete_zip=True)
                if extracted:
                    result[str(year)] = str(extracted)
                else:
                    logger.warning("[%s] Не удалось извлечь PDF из %s — оставлен архив.", ticker, filename)
            else:
                logger.warning(
                    "[%s] Неизвестный тип файла %s — оставлен как есть. Добавьте обработку вручную.",
                    ticker, filename,
                )

        except requests.HTTPError as exc:
            logger.error("[%s] HTTP-ошибка %s: %s", ticker, report.file_url, exc)
        except requests.RequestException as exc:
            logger.error("[%s] Ошибка сети %s: %s", ticker, report.file_url, exc)
        except OSError as exc:
            logger.error("[%s] Ошибка записи %s: %s", ticker, dest, exc)

    return result
