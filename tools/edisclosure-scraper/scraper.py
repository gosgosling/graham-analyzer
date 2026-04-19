"""
Парсер страниц e-disclosure.ru на базе Playwright (headless Chromium).

e-disclosure.ru защищён ServicePipe — JavaScript-челленджем, поэтому
простой requests не проходит. Playwright запускает полноценный браузер
Chromium в безголовом режиме, автоматически проходит JS-проверку и
получает реальный HTML-контент страницы.

Страница консолидированной отчётности компании:
  https://www.e-disclosure.ru/portal/files.aspx?id=<ID>&type=4

Структура таблицы:
  № | Тип документа | Отчётный период | Дата основания | Дата размещения | Файл

Скачиваем только строки, где:
  - тип документа содержит «Годовая»
  - отчётный период — это просто год (например, «2024»), без «месяцев»
"""

import logging
import re
import time
import random
from dataclasses import dataclass

from bs4 import BeautifulSoup

from config import (
    ANNUAL_KEYWORDS,
    EDISCLOSURE_BASE_URL,
    CONSOLIDATED_REPORT_TYPE,
    PAGE_DELAY_MIN,
    PAGE_DELAY_MAX,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

# Паттерн «только год»: 2024, 2023 — но не «2024, 9 месяцев»
_YEAR_ONLY = re.compile(r"^\d{4}$")


@dataclass
class ReportEntry:
    doc_type: str
    period: str
    year: int
    file_url: str
    file_label: str   # например «zip, 1.88 МБ»


def fetch_annual_reports(company_id: int, ticker: str) -> list[ReportEntry]:
    """
    Открывает страницу консолидированной отчётности через Playwright,
    дожидается прохождения JS-челленджа ServicePipe и возвращает
    список ГОДОВЫХ (не промежуточных) консолидированных отчётов.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    url = f"{EDISCLOSURE_BASE_URL}/portal/files.aspx?id={company_id}&type={CONSOLIDATED_REPORT_TYPE}"

    delay = random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
    logger.debug("[%s] Ждём %.1f с перед запросом страницы...", ticker, delay)
    time.sleep(delay)

    try:
        with sync_playwright() as pw:
            launch_kw = {
                "headless": True,
                "args": [
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ],
            }
            ep = pw.chromium.executable_path
            if ep:
                launch_kw["executable_path"] = ep
            browser = pw.chromium.launch(**launch_kw)
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            logger.debug("[%s] Открываем %s", ticker, url)
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)

            # Ждём, пока ServicePipe-challenge пройдёт:
            # страница должна содержать таблицу или текст «Консолидированная»
            try:
                page.wait_for_selector("table", timeout=30_000)
            except PWTimeoutError:
                # Возможно, страница без таблиц (нет отчётов) — берём HTML как есть
                logger.debug("[%s] Таймаут ожидания таблицы.", ticker)

            html = page.content()
            browser.close()

    except Exception as exc:
        logger.error("[%s] Ошибка Playwright для %s: %s", ticker, url, exc)
        return []

    return _parse_reports_page(html, ticker)


def _parse_reports_page(html: str, ticker: str) -> list[ReportEntry]:
    soup = BeautifulSoup(html, "lxml")
    results: list[ReportEntry] = []

    tables = soup.find_all("table")
    if not tables:
        logger.warning("[%s] Таблицы не найдены на странице.", ticker)
        return []

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue

            doc_type = cells[1].get_text(strip=True)
            period   = cells[2].get_text(strip=True)

            # Фильтр 1: только годовые отчёты по типу документа
            is_annual = any(kw.lower() in doc_type.lower() for kw in ANNUAL_KEYWORDS)
            if not is_annual:
                continue

            # Фильтр 2: период — только год (не «2024, 9 месяцев»)
            period_clean = period.strip()
            if not _YEAR_ONLY.match(period_clean):
                continue

            year = int(period_clean)

            # Ссылка на файл
            file_cell = cells[5]
            link = file_cell.find("a")
            if not link:
                continue

            href = link.get("href", "")
            if not href.startswith("http"):
                href = EDISCLOSURE_BASE_URL + href

            file_label = link.get_text(strip=True)

            results.append(ReportEntry(
                doc_type=doc_type,
                period=period_clean,
                year=year,
                file_url=href,
                file_label=file_label,
            ))

    # Если за один год несколько записей — берём последнюю по порядку в таблице
    # (обычно это исправленная/дополненная версия, стоящая выше в таблице)
    seen_years: set[int] = set()
    deduped: list[ReportEntry] = []
    for entry in results:
        if entry.year not in seen_years:
            seen_years.add(entry.year)
            deduped.append(entry)
        else:
            logger.debug(
                "[%s] Пропускаем дубль за %d (%s).", ticker, entry.year, entry.doc_type
            )

    if deduped:
        logger.info("[%s] Найдено %d годовых консолидированных отчётов.", ticker, len(deduped))
    else:
        logger.warning("[%s] Годовые консолидированные отчёты не найдены.", ticker)

    return deduped
