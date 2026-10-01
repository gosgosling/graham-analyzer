#!/usr/bin/env python3
"""Даты раскрытия отчётов с e-disclosure — для поля `financial_reports.disclosed_at`.

Опорная на графике и LTM переключаются в день, когда отчёт стал известен рынку.
Раньше этот день выводился правилом (годовой — 31.12 + 120 дней, полугодие —
30.06 + 60 дней), и у компаний, раскрывающихся раньше, оценка по старому отчёту
жила лишние месяцы.

Берётся **самая ранняя** дата размещения по периоду: на странице бывают
повторные публикации и исправленные версии, а рынок узнал отчёт из первой.
Собирается только таблица, сами файлы не скачиваются.

Запуск (нужны живые cookies — save_cookies.py):
  cd tools/edisclosure-scraper
  ../../backend/venv/bin/python fetch_disclosure_dates.py            # все компании с отчётами
  ../../backend/venv/bin/python fetch_disclosure_dates.py CHMF LKOH  # выборочно

Результат дописывается в disclosure_dates.json по мере обхода: прерванный запуск
продолжается с того места, где остановился. В базу пишет отдельный шаг —
backend/scripts/apply_disclosure_dates.py.
"""
from __future__ import annotations

import json
import logging
import random
import re
import sys
import time
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

from config import (
    ANNUAL_KEYWORDS,
    CONSOLIDATED_REPORT_TYPE,
    EDISCLOSURE_BASE_URL,
    PAGE_DELAY_MAX,
    PAGE_DELAY_MIN,
)
from db_client import get_companies_from_db
from period_parse import parse_period_label
from scraper import _is_consolidated_doc

OUT = Path(__file__).with_name("disclosure_dates.json")
IDS = Path(__file__).with_name("company_ids.json")
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("dates")


def page_html(company_id: int) -> str:
    from playwright.sync_api import TimeoutError as PWTimeoutError

    from browser_session import ServicePipeBlockedError, get_context, is_challenge_html, save_storage_state

    url = f"{EDISCLOSURE_BASE_URL}/portal/files.aspx?id={company_id}&type={CONSOLIDATED_REPORT_TYPE}"
    page = get_context().new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_selector("table", timeout=45_000)
        except PWTimeoutError:
            pass
        if "xpvnsulc" in page.url or is_challenge_html(page.content()):
            page.wait_for_timeout(5_000)
        html = page.content()
    finally:
        page.close()
    if is_challenge_html(html) and "<table" not in html:
        raise ServicePipeBlockedError("captcha — обновите cookies через save_cookies.py")
    save_storage_state()
    return html


def earliest_dates(html: str) -> dict[str, str]:
    """period_key («2025», «2025_H1») → самая ранняя дата размещения, ISO."""
    out: dict[str, str] = {}
    soup = BeautifulSoup(html, "lxml")
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 6:
            continue
        doc_type = cells[1].get_text(strip=True)
        if not _is_consolidated_doc(doc_type):
            continue
        parsed = parse_period_label(cells[2].get_text(strip=True))
        if parsed is None or parsed.period_type not in ("annual", "semi_annual"):
            continue
        is_annual_doc = any(kw.lower() in doc_type.lower() for kw in ANNUAL_KEYWORDS)
        if is_annual_doc and parsed.period_type != "annual":
            continue
        found = DATE_RE.search(cells[4].get_text(strip=True))
        if not found:
            continue
        day, month, year = (int(x) for x in found.groups())
        iso = date(year, month, day).isoformat()
        key = parsed.period_key
        if key not in out or iso < out[key]:
            out[key] = iso
    return out


def main() -> int:
    wanted = {a.upper() for a in sys.argv[1:]}
    ids = {k: v["id"] for k, v in json.loads(IDS.read_text()).items() if isinstance(v, dict) and "id" in v}
    done = json.loads(OUT.read_text()) if OUT.exists() else {}

    tickers = sorted(wanted) if wanted else sorted({c.ticker for c in get_companies_from_db()})
    todo = [t for t in tickers if t in ids and (wanted or t not in done)]
    missing = [t for t in tickers if t not in ids]
    if missing:
        log.info("Нет id e-disclosure: %s", ", ".join(missing))
    log.info("К обходу: %d компаний", len(todo))

    for n, ticker in enumerate(todo, 1):
        time.sleep(random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX))
        try:
            dates = earliest_dates(page_html(ids[ticker]))
        except Exception as exc:  # noqa: BLE001 — один сбой не должен ронять обход
            log.info("[%d/%d] %s: ошибка — %s", n, len(todo), ticker, exc)
            if "captcha" in str(exc):
                return 2
            continue
        done[ticker] = dates
        OUT.write_text(json.dumps(done, ensure_ascii=False, indent=1, sort_keys=True))
        log.info("[%d/%d] %s: %d периодов", n, len(todo), ticker, len(dates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
