"""Раздел «Экономика»: ряды для страницы и снимок рынка на дату.

Ряды берутся из `macro_service` (бюджет, ФНБ, госдолг, инфляция, резервы,
платёжный баланс, ВВП) и из рядов, которые уже грузятся для других разделов:
курс доллара и Brent (`oil_service`). Ключевая ставка, ОФЗ и индексы — в
обзоре рынка (`market_overview`), страница берёт их оттуда.

**Снимок на дату** связывает три уровня: экономика тогда → рынок тогда →
компании, которые тогда стоили дешевле всего относительно своей опорной
стоимости. Опорная — та, что считалась бы в тот день (`valuation_segments`:
по отчётам, раскрытым к этой дате, и ставке, известной к ней), а не
сегодняшняя. Иначе снимок «2022 года» знал бы прибыль 2025-го.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.market import macro_service
from app.services.market.oil_service import BRENT, USDRUB

# Дневные ряды на странице не нужны по дням: за 13 лет это 3 400 точек на
# ряд. Неделя (последний день недели) даёт ту же картину в семь раз легче.
_DAILY = (USDRUB, "EURRUB", "CNYRUB", BRENT)
_DAILY_META = {
    USDRUB: macro_service.Series(USDRUB, "Доллар", "₽", "day", "ЦБ, официальный курс"),
    BRENT: macro_service.Series(BRENT, "Нефть Brent", "$/барр.", "day", "FRED (DCOILBRENTEU)"),
}


def _weekly(points: list[tuple[date, float]]) -> list[tuple[date, float]]:
    out: dict[tuple[int, int], tuple[date, float]] = {}
    for day, value in points:
        out[day.isocalendar()[:2]] = (day, value)
    weekly = list(out.values())
    # Последний день — всегда сам по себе: это «сейчас» на странице.
    if points and weekly[-1] != points[-1]:
        weekly.append(points[-1])
    return weekly


def _pairs(points, digits: int = 2) -> list:
    return [[d.isoformat(), round(v, digits)] for d, v in points]


def macro(db: Session) -> dict:
    codes = list(macro_service.SERIES) + [USDRUB, BRENT]
    raw = macro_service.load(db, codes)
    meta = {**macro_service.SERIES, **_DAILY_META}
    series = {}
    for code, points in raw.items():
        if code in _DAILY:
            points = [(d, v) for d, v in points if d >= date(2013, 1, 1)]
            points = _weekly(points)
        series[code] = _pairs(points, 4 if code in _DAILY else 2)

    budget = {}
    for code, _label in macro_service.BUDGET_ROWS.values():
        month, rolling = macro_service.budget_flows(raw.get(code, []))
        budget[code] = {"month": _pairs(month, 1), "rolling": _pairs(rolling, 1)}

    return {
        "meta": {
            code: {"label": s.label, "unit": s.unit, "freq": s.freq, "source": s.source}
            for code, s in meta.items()
        },
        "series": series,
        "budget": budget,
        "budget_law": {
            str(year): {"revenue": rev * 1000, "expense": exp * 1000, "balance": bal * 1000}
            for year, (rev, exp, bal) in macro_service.BUDGET_LAW.items()
        },
        "as_of": date.today().isoformat(),
    }


def _prices_on(db: Session, ids: list[int], on: date) -> dict[int, tuple[date, float]]:
    """Последняя цена не позже даты — но не старше двух недель: бумага,
    которая тогда не торговалась, в снимок не попадает."""
    rows = db.execute(text(
        "select distinct on (company_id) company_id, date, price from stock_prices "
        "where company_id = any(:ids) and date <= :on and date >= :since "
        "order by company_id, date desc"
    ), {"ids": ids, "on": on, "since": on - timedelta(days=14)}).fetchall()
    return {cid: (day, float(price)) for cid, day, price in rows}


def _latest_prices(db: Session, ids: list[int]) -> dict[int, tuple[date, float]]:
    rows = db.execute(text(
        "select distinct on (company_id) company_id, date, price from stock_prices "
        "where company_id = any(:ids) order by company_id, date desc"
    ), {"ids": ids}).fetchall()
    return {cid: (day, float(price)) for cid, day, price in rows}


def _segment_on(segments: list[dict], on: date) -> Optional[dict]:
    iso = on.isoformat()
    for seg in segments:
        if seg["from"] <= iso <= seg["till"] and not seg.get("refused") and seg.get("reference"):
            return seg
    return None


def companies_on(db: Session, on: date) -> dict:
    """Компании на дату: цена тогда против опорной тогда и что с ценой стало.

    Цена приводится к сегодняшнему числу акций (как на графике в карточке):
    опорная в отрезках посчитана на нынешние акции, и у Белуги до дробления
    8:1 иначе вышла бы «дороже в восемь раз»."""
    from app.models.company import Company
    from app.routers.valuation_router import company_valuation_history
    from app.services.analysis.market_snapshot import trustworthy_tickers
    from app.services.share_splits import company_splits, shares_factor

    companies = db.query(Company).filter(Company.ticker.in_(trustworthy_tickers(db))).all()
    ids = [c.id for c in companies]
    then, latest = _prices_on(db, ids, on), _latest_prices(db, ids)
    rows = []
    for company in companies:
        if company.id not in then:
            continue
        try:
            history = company_valuation_history(company_id=company.id, db=db)
        except Exception:  # noqa: BLE001 — одна компания не срывает снимок
            continue
        seg = _segment_on(history.get("segments") or [], on)
        if seg is None:
            continue
        splits = company_splits(db, company)
        day, price = then[company.id]
        price /= shares_factor(splits, day)
        now_day, now_price = latest.get(company.id, (None, None))
        if company.current_price:
            now_price = float(company.current_price)
        rows.append({
            "id": company.id,
            "ticker": company.ticker,
            "name": company.name,
            "price": round(price, 4),
            "price_date": day.isoformat(),
            "reference": round(float(seg["reference"]), 4),
            "low": seg.get("low"),
            "high": seg.get("high"),
            "basis": seg.get("basis"),
            "risk_free": seg.get("risk_free"),
            "price_now": round(now_price, 4) if now_price else None,
            "change": round((now_price / price - 1) * 100, 1) if now_price and price else None,
        })
    rows.sort(key=lambda r: r["price"] / r["reference"])
    return {"on": on.isoformat(), "rows": rows}
