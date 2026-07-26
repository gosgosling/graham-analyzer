"""
Парсер страниц e-disclosure.ru на базе Playwright (headless Chromium).

Страница консолидированной отчётности:
  https://www.e-disclosure.ru/portal/files.aspx?id=<ID>&type=4

Структура таблицы:
  № | Тип документа | Отчётный период | Дата основания | Дата размещения | Файл
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import asdict, dataclass
from typing import Optional

from bs4 import BeautifulSoup

from config import (
    ANNUAL_KEYWORDS,
    CONSOLIDATED_KEYWORDS,
    EXCLUDE_DOC_KEYWORDS,
    EDISCLOSURE_BASE_URL,
    CONSOLIDATED_REPORT_TYPE,
    PAGE_DELAY_MIN,
    PAGE_DELAY_MAX,
    USER_AGENT,
)
from period_parse import ParsedPeriod, parse_period_label

logger = logging.getLogger(__name__)


@dataclass
class ReportEntry:
    doc_type: str
    period: str
    year: int  # = fiscal_year (compat)
    fiscal_year: int
    period_type: str
    fiscal_quarter: Optional[int]
    period_key: str
    interim_rank: int
    file_url: str
    file_label: str
    published_at: Optional[str] = None  # дата размещения, как в таблице

    def to_dict(self) -> dict:
        return asdict(self)


def fetch_annual_reports(company_id: int, ticker: str) -> list[ReportEntry]:
    """Обратная совместимость: только годовые."""
    return [
        e for e in fetch_all_reports(company_id, ticker) if e.period_type == "annual"
    ]


def fetch_all_reports(company_id: int, ticker: str) -> list[ReportEntry]:
    """Все консолидированные периоды (годовые + промежуточные) с страницы type=4."""
    from playwright.sync_api import TimeoutError as PWTimeoutError

    from browser_session import (
        ServicePipeBlockedError,
        get_context,
        is_challenge_html,
        save_storage_state,
    )

    url = (
        f"{EDISCLOSURE_BASE_URL}/portal/files.aspx"
        f"?id={company_id}&type={CONSOLIDATED_REPORT_TYPE}"
    )

    delay = random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX)
    logger.debug("[%s] Ждём %.1f с перед запросом страницы...", ticker, delay)
    time.sleep(delay)

    try:
        context = get_context()
        page = context.new_page()
        try:
            logger.debug("[%s] Открываем %s", ticker, url)
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            try:
                page.wait_for_selector("table", timeout=45_000)
            except PWTimeoutError:
                logger.debug("[%s] Таймаут ожидания таблицы.", ticker)
            # ServicePipe иногда редиректит на captcha — даём JS ещё чуть времени
            if "xpvnsulc" in page.url or is_challenge_html(page.content()):
                page.wait_for_timeout(5_000)
            html = page.content()
        finally:
            page.close()

        if is_challenge_html(html) and "<table" not in html:
            raise ServicePipeBlockedError(
                f"[{ticker}] ServicePipe captcha/challenge — listing недоступен. "
                f"Решите captcha в браузере и положите cookies в "
                f"tools/edisclosure-scraper/.edisclosure_storage_state.json "
                f"или импортируйте listing через --list-json / POST /disclosure/import-listing."
            )

        save_storage_state()
    except ServicePipeBlockedError:
        raise
    except Exception as exc:
        logger.error("[%s] Ошибка Playwright для %s: %s", ticker, url, exc)
        return []

    return _parse_reports_page(html, ticker)


def _is_consolidated_doc(doc_type: str) -> bool:
    low = doc_type.lower()
    if any(ex.lower() in low for ex in EXCLUDE_DOC_KEYWORDS):
        return False
    # Годовые — старые keywords; промежуточные — «консолидир» без «сводн»
    if any(kw.lower() in low for kw in ANNUAL_KEYWORDS):
        return True
    if any(kw.lower() in low for kw in CONSOLIDATED_KEYWORDS):
        return True
    return "консолидир" in low and "сводн" not in low


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
            period = cells[2].get_text(strip=True)
            published = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            if not _is_consolidated_doc(doc_type):
                continue

            parsed = parse_period_label(period)
            if parsed is None:
                logger.debug("[%s] Не разобран период %r (%s)", ticker, period, doc_type)
                continue

            # Годовой тип документа, но период промежуточный — доверяем периоду
            # Промежуточный период при «Годовая консолидированная» — странно, пропускаем mismatch
            is_annual_doc = any(kw.lower() in doc_type.lower() for kw in ANNUAL_KEYWORDS)
            if is_annual_doc and parsed.period_type != "annual":
                continue
            if (not is_annual_doc) and parsed.period_type == "annual":
                # «Промежуточная…» с периодом «2024» — редкость; всё же примем как annual
                pass

            file_cell = cells[5]
            link = file_cell.find("a")
            if not link:
                continue

            href = link.get("href", "")
            if not href.startswith("http"):
                href = EDISCLOSURE_BASE_URL + href

            results.append(
                ReportEntry(
                    doc_type=doc_type,
                    period=period.strip(),
                    year=parsed.fiscal_year,
                    fiscal_year=parsed.fiscal_year,
                    period_type=parsed.period_type,
                    fiscal_quarter=parsed.fiscal_quarter,
                    period_key=parsed.period_key,
                    interim_rank=parsed.interim_rank,
                    file_url=href,
                    file_label=link.get_text(strip=True),
                    published_at=published or None,
                )
            )

    # Дедуп по period_key — первая строка в таблице (обычно свежее)
    seen: set[str] = set()
    deduped: list[ReportEntry] = []
    for entry in results:
        if entry.period_key in seen:
            logger.debug(
                "[%s] Пропускаем дубль %s (%s).",
                ticker,
                entry.period_key,
                entry.doc_type,
            )
            continue
        seen.add(entry.period_key)
        deduped.append(entry)

    logger.info(
        "[%s] Найдено %d консолидированных периодов (annual=%d, interim=%d).",
        ticker,
        len(deduped),
        sum(1 for e in deduped if e.period_type == "annual"),
        sum(1 for e in deduped if e.period_type != "annual"),
    )
    return deduped
