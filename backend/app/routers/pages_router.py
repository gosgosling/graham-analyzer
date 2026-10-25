"""Страницы сайта для тех, кто не выполняет JavaScript: поисковики и превью ссылок.

Сайт — одностраничное приложение: на любой адрес сервер отдавал один и тот же
`index.html` с заголовком «Graham Analyzer», а содержимое достраивал скрипт в
браузере. Человек этого не замечал. Робот Telegram, ВК или поисковика видел
пустую оболочку: у ссылки на Сбербанк и на Лукойл было одно и то же безликое
превью, страницы компаний в поиске не находились, а `/sitemap.xml` отвечал той
же пустой страницей с кодом 200.

Здесь `index.html` той же сборки дополняется под адрес:

* `<title>`, `description`, `og:*` — название компании и её цифры в превью;
* короткий текст с цифрами и ссылками внутри `#root` — его видит робот без
  скрипта; React при запуске заменяет его страницей, как и раньше;
* код 404 для несуществующей компании и неизвестного адреса — иначе
  поисковик принимает такие адреса за дубли главной;
* `noindex` для входа, кабинета и служебных страниц.

Caddy отдаёт файлы сборки сам, а всё остальное присылает сюда с префиксом
`/_page`. Сам `index.html` берётся у Caddy со внутреннего адреса
(`WEB_INDEX_URL`) и держится в памяти минуту: после выката подхватывается
новая сборка, а на каждый запрос его не перечитываем.

Полный пререндер (вся страница компании в HTML) — следующий шаг; превью и
основу для поиска закрывает и это.
"""
from __future__ import annotations

import html
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company

logger = logging.getLogger(__name__)

router = APIRouter(include_in_schema=False)

SITE_NAME = "Graham Analyzer"
DEFAULT_DESCRIPTION = (
    "Стоимость российских акций по методу Грэма и Додда — из отчётов МСФО за много лет, "
    "без прогнозов аналитиков и без рекомендаций."
)
INDEX_URL = os.getenv("WEB_INDEX_URL", "http://web:8080/index.html")
INDEX_TTL = 60.0

_index_lock = threading.Lock()
_index: tuple[float, str] | None = None

# Разделы, которые показываются всем и стоят в карте сайта.
PUBLIC = {
    "": ("Оценка российских акций по Грэму", DEFAULT_DESCRIPTION),
    "companies": ("Российские акции: оценка по отчётам МСФО", "Российские компании с отчётностью МСФО за много лет: цена, опорная стоимость по Грэму, дивиденды и мультипликаторы."),
    "screen": ("Скринер акций по Грэму", "Требования Грэма к защитному и активному инвестору: какие российские компании проходят отбор и чего не хватило остальным."),
    "market": ("Рынок акций РФ: P/E и доходность против ОФЗ", "P/E российского рынка за двадцать лет и сколько акции зарабатывают против облигаций."),
    "economy": ("Экономика", "Бюджет, госдолг, ФНБ, инфляция, ставка, курс и настроения людей — и снимок на любую дату: что было с рынком и компаниями тогда."),
    "calendar": ("Календарь отчётности", "Когда российские компании публикуют МСФО и чьи цифры уже обновились."),
    "valuation": ("Как считается стоимость", "Метод Грэма и Додда по шагам: от средней прибыли до запаса прочности."),
    "compare": ("Сравнение компаний", "Российские компании рядом: оценка, рентабельность, долг и дивиденды."),
    "privacy": ("Политика конфиденциальности", DEFAULT_DESCRIPTION),
    "consent": ("Согласие на обработку данных", DEFAULT_DESCRIPTION),
}
# Существуют, но в поиске им делать нечего.
PRIVATE = {
    "login": "Вход", "register": "Регистрация", "forgot": "Восстановление пароля",
    "reset": "Новый пароль", "verify": "Подтверждение почты", "verify-email": "Подтверждение почты",
    "account": "Кабинет", "admin": "Админ", "securities": "Бумаги", "bonds": "Облигации",
    "mass-parse": "Разбор отчётов", "disclosure": "Раскрытие",
}
SITEMAP_SECTIONS = ("", "companies", "screen", "market", "economy", "calendar", "valuation")


@dataclass
class Page:
    title: str
    description: str
    status: int = 200
    noindex: bool = False
    heading: Optional[str] = None
    lines: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)


# ─── Числа ──────────────────────────────────────────────────────────────────


def _ru(value: float, digits: int = 0) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text.replace("-", "−")


def _price(value: float) -> str:
    if abs(value) >= 100:
        return _ru(value, 0)
    if abs(value) >= 1:
        return _ru(value, 2)
    return _ru(value, 4)


def _gap(price: float, reference: float) -> str:
    if price >= reference * 2:
        return f"дороже в {_ru(price / reference, 1)} раза"
    pct = round(abs(price / reference - 1) * 100)
    return f"{'дешевле' if price < reference else 'дороже'} на {pct}%"


def _screen_rows(db: Session) -> dict[int, dict]:
    """Строки скринера по проверенным компаниям — из кэша, его греет прогрев."""
    try:
        from app.routers.screen_router import market_screen

        return {row["id"]: row for row in market_screen(standard="defensive", all_companies=False, db=db)["rows"]}
    except Exception as exc:  # noqa: BLE001 — без цифр страница всё равно отдаётся
        logger.warning("Страница: скринер не посчитался: %s", exc)
        return {}


# ─── Страницы ───────────────────────────────────────────────────────────────


def _company_page(db: Session, company: Company) -> Page:
    name = company.name
    # Та же сводка, что в карточке (и в том же кэше): числа в превью
    # совпадают с тем, что человек увидит, открыв ссылку.
    try:
        from app.routers.valuation_router import DEFAULT_WINDOW, company_summary

        summary = company_summary(company_id=company.id, window=DEFAULT_WINDOW, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Страница компании %s: сводка не посчиталась: %s", company.ticker, exc)
        summary = {}
    safety = summary.get("safety") or {}
    headline = summary.get("headline") or {}
    price = safety.get("price") or summary.get("price") or (float(company.current_price) if company.current_price else None)
    reference = safety.get("reference") or headline.get("reference")
    lines = []
    if price and reference:
        lines.append(f"Цена {_price(price)} ₽, опорная стоимость по Грэму {_price(reference)} ₽ — {_gap(price, reference)}.")
        if safety.get("screen_clears"):
            lines.append("Проходит отбор Грэма для защитного инвестора.")
    elif price:
        lines.append(f"Цена {_price(price)} ₽.")
    figures = _multipliers(db, company)
    if figures:
        lines.append(figures)
    lines.append("Отчётность МСФО за много лет, оценка по методу Грэма и Додда, дивиденды и мультипликаторы.")
    # Описание для превью — короче: цена против опорной и мультипликаторы.
    description = " ".join(lines[:3]) if len(lines) > 2 else " ".join(lines)
    peers = _peers(db, company)
    return Page(
        title=f"{name} ({company.ticker}): оценка по Грэму, P/E, дивиденды",
        description=description,
        heading=f"{name} ({company.ticker})",
        lines=lines,
        links=peers + [("/companies", "Все компании"), ("/screen", "Скринер акций по Грэму")],
    )


def _multipliers(db: Session, company: Company) -> Optional[str]:
    """«P/E 3,3, P/B 0,72, дивидендная доходность 13,1%, ROE 21,9%» — последние
    текущие мультипликаторы, те же, что в столбце «12 мес.» карточки."""
    from app.models.multiplier import Multiplier

    row = (db.query(Multiplier)
           .filter(Multiplier.company_id == company.id, Multiplier.type == "current")
           .order_by(Multiplier.date.desc()).first())
    if row is None:
        return None
    parts = []
    if row.pe_ratio is not None and float(row.pe_ratio) > 0:
        parts.append(f"P/E {_ru(float(row.pe_ratio), 1)}")
    if row.pb_ratio is not None and float(row.pb_ratio) > 0:
        parts.append(f"P/B {_ru(float(row.pb_ratio), 2)}")
    if row.dividend_yield is not None and float(row.dividend_yield) > 0:
        parts.append(f"дивидендная доходность {_ru(float(row.dividend_yield), 1)}%")
    if row.roe is not None:
        parts.append(f"ROE {_ru(float(row.roe), 1)}%")
    if row.market_cap:
        parts.append(f"капитализация {_ru(float(row.market_cap) / 1e6, 2)} трлн ₽"
                     if float(row.market_cap) >= 1e6 else f"капитализация {_ru(float(row.market_cap) / 1e3, 0)} млрд ₽")
    return (", ".join(parts)[:1].upper() + ", ".join(parts)[1:] + ".") if parts else None


def _peers(db: Session, company: Company) -> list[tuple[str, str]]:
    """До пяти компаний той же отрасли — перелинковка для поисковика."""
    try:
        from app.routers.compare_router import company_peers

        others = [c for c in company_peers(company_id=company.id, db=db)["companies"] if c["id"] != company.id]
    except Exception:  # noqa: BLE001
        return []
    return [(f"/company/{c['id']}", f"{c['name']} ({c['ticker']})") for c in others[:5]]


def _market_page(db: Session) -> Page:
    title, description = PUBLIC["market"]
    lines = []
    try:
        from app.routers.market_router import market_overview

        now = next((y for y in market_overview(db=db)["valuation"] if y["year"] == "now"), None)
        if now:
            line = f"P/E рынка {_ru(now['pe'], 1)}, доходность прибыли {_ru(now['earnings_yield'], 1)}%"
            if now.get("ofz10") is not None:
                line += f" против {_ru(now['ofz10'], 1)}% у десятилетних ОФЗ"
            lines.append(line + ".")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Страница рынка: обзор не посчитался: %s", exc)
    return Page(title=title, description=" ".join(lines + [description]), heading="Рынок", lines=lines + [description])


def _screen_page(db: Session) -> Page:
    title, description = PUBLIC["screen"]
    rows = list(_screen_rows(db).values())
    lines = [description]
    if rows:
        cleared = [r for r in rows if r.get("clears")]
        lines.insert(0, f"Отбор проходят {len(cleared)} из {len(rows)} компаний.")
    links = [(f"/company/{r['id']}", r["name"]) for r in rows if r.get("clears")][:20]
    return Page(title=title, description=" ".join(lines), heading=title, lines=lines, links=links)


def _economy_page(db: Session) -> Page:
    title, description = PUBLIC["economy"]
    lines = []
    try:
        from app.routers.market_router import macro

        series = macro(db=db)["series"]
        infl = series.get("M_INFL") or []
        if infl:
            lines.append(f"Инфляция {_ru(infl[-1][1], 2)}% год к году.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Страница экономики: ряды не посчитались: %s", exc)
    return Page(title="Экономика России: бюджет, долг, инфляция", description=" ".join(lines + [description]),
                heading="Экономика", lines=lines + [description])


def resolve(db: Session, path: str) -> Page:
    parts = [p for p in path.strip("/").split("/") if p]
    head = parts[0] if parts else ""

    if head == "company" and len(parts) >= 2:
        company = db.query(Company).filter(Company.id == int(parts[1])).first() if parts[1].isdigit() else None
        if company is None:
            return Page(title="Компания не найдена", description=DEFAULT_DESCRIPTION, status=404, noindex=True)
        page = _company_page(db, company)
        if len(parts) > 2:  # служебные подстраницы карточки
            page.noindex = True
        return page
    if head == "bond" and len(parts) >= 2:
        return Page(title="Облигация", description=DEFAULT_DESCRIPTION, noindex=True)
    if len(parts) > 1:
        return Page(title="Страница не найдена", description=DEFAULT_DESCRIPTION, status=404, noindex=True)
    if head == "market":
        return _market_page(db)
    if head == "screen":
        return _screen_page(db)
    if head == "economy":
        return _economy_page(db)
    if head in PUBLIC:
        title, description = PUBLIC[head]
        return Page(title=title, description=description, heading=title, lines=[description])
    if head in PRIVATE:
        return Page(title=PRIVATE[head], description=DEFAULT_DESCRIPTION, noindex=True)
    return Page(title="Страница не найдена", description=DEFAULT_DESCRIPTION, status=404, noindex=True)


# ─── HTML ───────────────────────────────────────────────────────────────────


def _load_index() -> Optional[str]:
    global _index  # noqa: PLW0603
    with _index_lock:
        if _index and time.monotonic() - _index[0] < INDEX_TTL:
            return _index[1]
    try:
        # Прокси окружения мимо: сборка лежит во внутренней сети.
        session = requests.Session()
        session.trust_env = False
        response = session.get(INDEX_URL, timeout=5)
        response.raise_for_status()
        text = response.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("index.html со сборки не получен (%s): %s", INDEX_URL, exc)
        return _index[1] if _index else None
    with _index_lock:
        _index = (time.monotonic(), text)
    return text


def _base_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "graham-analyzer.ru"
    proto = request.headers.get("x-forwarded-proto") or "https"
    return f"{proto}://{host.split(',')[0].strip()}"


def render(index: str, page: Page, url: str, base: str) -> str:
    esc = html.escape
    title = page.title if page.title == SITE_NAME else f"{page.title} — {SITE_NAME}"
    head = [
        f'<meta property="og:title" content="{esc(page.title)}" />',
        f'<meta property="og:description" content="{esc(page.description)}" />',
        '<meta property="og:type" content="website" />',
        f'<meta property="og:site_name" content="{SITE_NAME}" />',
        '<meta property="og:locale" content="ru_RU" />',
        f'<meta property="og:url" content="{esc(url)}" />',
        f'<meta property="og:image" content="{esc(base)}/logo512.png" />',
        '<meta name="twitter:card" content="summary" />',
        f'<link rel="canonical" href="{esc(url)}" />',
    ]
    if page.noindex:
        head.append('<meta name="robots" content="noindex" />')

    out = re.sub(r"<title>.*?</title>", f"<title>{esc(title)}</title>", index, count=1, flags=re.S)
    out = re.sub(r'(<meta\s+name="description"\s+content=")[^"]*(")',
                 lambda m: m.group(1) + esc(page.description) + m.group(2), out, count=1)
    out = out.replace("</head>", "\n".join(head) + "\n</head>", 1)

    # Текст для робота — внутри #root: React при запуске его заменит.
    if page.heading or page.lines:
        body = [f"<h1>{esc(page.heading or page.title)}</h1>"]
        body += [f"<p>{esc(line)}</p>" for line in page.lines]
        if page.links:
            body.append("<ul>" + "".join(f'<li><a href="{esc(href)}">{esc(text)}</a></li>' for href, text in page.links) + "</ul>")
        block = ('<div id="root"><main style="max-width:760px;margin:48px auto;padding:0 16px;'
                 'font-family:system-ui,sans-serif;line-height:1.5">' + "".join(body) + "</main></div>")
        out = re.sub(r'<div id="root">\s*</div>', lambda _m: block, out, count=1)
    return out


@router.get("/_page/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)) -> Response:
    base = _base_url(request)
    urls = [f"{base}/{section}" for section in SITEMAP_SECTIONS]
    urls += [f"{base}/company/{cid}" for (cid,) in db.query(Company.id).order_by(Company.id)]
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    # Без lastmod: дата «сегодня» у всех адресов поисковику ничего не говорит,
    # а настоящей даты изменения страницы у нас нет.
    body += [f"<url><loc>{html.escape(u)}</loc></url>" for u in urls]
    body.append("</urlset>")
    return Response("\n".join(body), media_type="application/xml")


@router.get("/_page/{path:path}")
@router.get("/_page")
def page(request: Request, path: str = "", db: Session = Depends(get_db)) -> Response:
    index = _load_index()
    try:
        info = resolve(db, path)
    except Exception as exc:  # noqa: BLE001 — страница отдаётся всегда, хоть и без цифр
        logger.warning("Страница /%s: %s", path, exc)
        info = Page(title=SITE_NAME, description=DEFAULT_DESCRIPTION)
    if index is None:
        return HTMLResponse("<!doctype html><title>Graham Analyzer</title><p>Сайт обновляется, зайдите через минуту.</p>",
                            status_code=503)
    base = _base_url(request)
    url = base + ("/" + path.strip("/") if path.strip("/") else "/")
    return HTMLResponse(render(index, info, url, base), status_code=info.status,
                        headers={"Cache-Control": "no-cache"})
