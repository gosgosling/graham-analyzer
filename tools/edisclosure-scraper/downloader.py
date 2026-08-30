"""
Загрузка файлов с e-disclosure.ru → TICKER_{period_key}.pdf
"""

from __future__ import annotations

import json
import logging
from typing import Optional
import random
import shutil
import time
from pathlib import Path

import requests

from config import FILE_DELAY_MIN, FILE_DELAY_MAX, REPORTS_BASE_DIR, USER_AGENT
from pdf_extract import (
    extract_main_pdf_from_zip,
    pdf_target_path,
    process_orphan_zips_in_ticker_dir,
)
from scraper import ReportEntry

logger = logging.getLogger(__name__)

_sp_cookies: dict[str, str] = {}


def _cookies_from_storage_state() -> dict[str, str]:
    """Cookies из файла, который пишет `save_cookies.py` после ручной captcha.

    Это единственный источник, переживающий ServicePipe: свежий headless-браузер
    получает challenge и уходит с пустыми руками, а сессия, в которой человек
    прошёл проверку, работает. Раньше файл не читался вовсе — из-за этого
    скачивание молча возвращало ноль даже сразу после успешного save_cookies.
    """
    from browser_session import STORAGE_STATE_PATH

    if not STORAGE_STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STORAGE_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Не удалось прочитать storage_state: %s", exc)
        return {}
    out = {
        c["name"]: c["value"]
        for c in data.get("cookies", [])
        if "e-disclosure" in str(c.get("domain", ""))
    }
    if out:
        logger.info("Взято %d cookies из storage_state.", len(out))
    return out


def _get_sp_cookies() -> dict[str, str]:
    global _sp_cookies
    if _sp_cookies:
        return _sp_cookies

    # Сначала — сохранённая сессия с пройденной captcha.
    saved = _cookies_from_storage_state()
    if saved:
        _sp_cookies = saved
        return _sp_cookies

    from playwright.sync_api import sync_playwright

    logger.info("storage_state пуст — пробуем получить cookies браузером...")
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
            page.goto(
                "https://www.e-disclosure.ru/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
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
    return f"{report.period_key}_consolidated.{ext}"


def _download_to_path(session: requests.Session, url: str, dest: Path) -> None:
    resp = session.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)


def _note(errors: Optional[list[str]], message: str) -> None:
    """Причина неудачи — наверх, а не только в лог."""
    if errors is not None:
        errors.append(message)


def download_reports(
    ticker: str,
    reports: list[ReportEntry],
    errors: Optional[list[str]] = None,
) -> dict[str, str]:
    """
    Скачивает отчёты → TICKER_{period_key}.pdf.
    Возвращает {period_key: path}.

    `errors` — список, куда складываются причины неудач. Без него сбой попадал
    только в лог, а вызывающая сторона видела «скачано 0, ошибок нет» и не
    могла отличить «всё уже на диске» от «сервер вернул captcha».
    """
    if not reports:
        return {}

    ticker_dir = _ticker_dir(ticker)
    process_orphan_zips_in_ticker_dir(ticker, ticker_dir)

    session = _make_session()
    result: dict[str, str] = {}

    for report in sorted(
        reports,
        key=lambda r: (r.fiscal_year, r.interim_rank),
        reverse=True,
    ):
        key = report.period_key
        pdf_path = pdf_target_path(ticker, report.year, ticker_dir, period_key=key)

        if pdf_path.exists():
            logger.info("[%s] PDF %s уже есть — %s", ticker, key, pdf_path.name)
            result[key] = str(pdf_path)
            continue

        filename = _filename_for(report)
        dest = ticker_dir / filename

        if dest.exists() and dest.suffix.lower() == ".zip":
            extracted = extract_main_pdf_from_zip(
                dest, ticker, report.year, ticker_dir, delete_zip=True, period_key=key
            )
            if extracted:
                result[key] = str(extracted)
            continue

        if dest.exists() and dest.suffix.lower() == ".pdf":
            shutil.copy2(dest, pdf_path)
            if dest != pdf_path:
                dest.unlink(missing_ok=True)
            logger.info("[%s] ✓ Сохранён %s", ticker, pdf_path.name)
            result[key] = str(pdf_path)
            continue

        delay = random.uniform(FILE_DELAY_MIN, FILE_DELAY_MAX)
        time.sleep(delay)

        logger.info("[%s] Скачиваем %s → %s", ticker, report.file_url, filename)
        try:
            _download_to_path(session, report.file_url, dest)
            size_kb = dest.stat().st_size / 1024
            logger.info("[%s] ✓ Временный %s (%.0f КБ)", ticker, filename, size_kb)

            suffix = dest.suffix.lower()
            if suffix == ".pdf":
                shutil.copy2(dest, pdf_path)
                dest.unlink(missing_ok=True)
                logger.info("[%s] ✓ Сохранён %s", ticker, pdf_path.name)
                result[key] = str(pdf_path)
            elif suffix == ".zip":
                extracted = extract_main_pdf_from_zip(
                    dest, ticker, report.year, ticker_dir, delete_zip=True, period_key=key
                )
                if extracted:
                    result[key] = str(extracted)
                else:
                    logger.warning("[%s] Не удалось извлечь PDF из %s", ticker, filename)
                    _note(errors, f"{ticker} {key}: в архиве нет PDF")
            else:
                logger.warning("[%s] Неизвестный тип %s", ticker, filename)
                _note(errors, f"{ticker} {key}: неизвестный тип файла {suffix}")

        except requests.HTTPError as exc:
            logger.error("[%s] HTTP-ошибка %s: %s", ticker, report.file_url, exc)
            _note(errors, f"{ticker} {key}: HTTP {exc}")
        except requests.RequestException as exc:
            logger.error("[%s] Ошибка сети %s: %s", ticker, report.file_url, exc)
            _note(errors, f"{ticker} {key}: сеть — {exc}")
        except OSError as exc:
            logger.error("[%s] Ошибка записи %s: %s", ticker, dest, exc)
            _note(errors, f"{ticker} {key}: запись — {exc}")

    return result
