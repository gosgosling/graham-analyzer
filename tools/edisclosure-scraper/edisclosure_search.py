"""
Поиск ID эмитента на www.e-disclosure.ru по ИНН или строке запроса.

Используется POST на /poisk-po-kompaniyam (как на форме «Поиск по компаниям»).
Из-за ServicePipe обычно нужна сессия браузера — см. search_company_id_playwright().
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

from bs4 import BeautifulSoup

from config import USER_AGENT

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.e-disclosure.ru/poisk-po-kompaniyam"

_ID_RE = re.compile(r"company\.aspx\?id=(\d+)", re.IGNORECASE)


def parse_company_links_from_html(html: str) -> list[tuple[int, str]]:
    """Из HTML ответа поиска извлекает пары (id, название из ссылки)."""
    if len(html) < 500 and "spinner" in html and "servicepipe" in html.lower():
        return []
    soup = BeautifulSoup(html, "lxml")
    seen: set[int] = set()
    out: list[tuple[int, str]] = []
    for a in soup.select("a[href*='company.aspx?id=']"):
        href = a.get("href") or ""
        m = _ID_RE.search(href)
        if not m:
            continue
        cid = int(m.group(1))
        if cid in seen:
            continue
        seen.add(cid)
        title = a.get_text(strip=True) or ""
        out.append((cid, title))
    return out


def pick_best_match(
    rows: Iterable[tuple[int, str]],
    inn: str | None,
    moex_title: str | None,
) -> int | None:
    """Если поиск по ИНН — обычно первая строка верна; иначе эвристика по названию."""
    rows = list(rows)
    if not rows:
        return None
    if inn and len(rows) == 1:
        return rows[0][0]
    if moex_title:
        mt = moex_title.lower()
        best = None
        best_score = -1
        for cid, title in rows:
            t = title.lower()
            score = 0
            if mt[:40] in t or t[:40] in mt:
                score += 10
            score += len(set(mt.split()) & set(t.split()))
            if score > best_score:
                best_score = score
                best = cid
        if best is not None and best_score > 0:
            return best
    return rows[0][0]


def search_company_id_playwright(
    query: str,
    moex_title: str | None = None,
) -> int | None:
    """
    Открывает страницу «Поиск по компаниям», вводит запрос в форму (как у пользователя).
    Прямой POST без полноценной страницы отдаёт заглушку ServicePipe — результаты
    подгружаются в DOM после нажатия «Искать».

    query — ИНН (предпочтительно) или фрагмент наименования.
    moex_title — название эмитента из MOEX для выбора среди нескольких результатов.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        # Явный путь к bundled Chromium: иначе на части окружений ищется
        # chromium_headless_shell и падает, если не установлен отдельно.
        launch_kw: dict = {
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
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=120_000)
        page.locator('input[name="textfield"]').wait_for(state="visible", timeout=90_000)
        try:
            page.locator("#AcceptCookieBtn").click(timeout=3000)
        except Exception:
            pass
        page.locator('input[name="textfield"]').fill(query)
        page.locator("#sendButton").click()
        try:
            page.wait_for_selector("a[href*='company.aspx?id=']", timeout=90_000)
        except Exception:
            pass
        html = page.content()
        browser.close()

    rows = parse_company_links_from_html(html)
    inn_digits = query if query.isdigit() and len(query) >= 10 else None
    return pick_best_match(rows, inn_digits, moex_title)
