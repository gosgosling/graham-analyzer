"""Индексы Мосбиржи: загрузка истории и ежедневное обновление.

Источник — ISS `history/engines/stock/markets/index/securities/{код}`.
История отдаётся страницами по сто строк, поэтому первая загрузка — несколько
десятков запросов на индекс; дальше ежедневная задача докачивает только
новые дни.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.market_index import MarketIndexValue
from app.utils.moex_client import _moex_get

logger = logging.getLogger(__name__)

_URL = "https://iss.moex.com/iss/history/engines/stock/markets/index/securities/{code}.json"

# Индекс Мосбиржи как торговался, он же полной доходности (дивиденды
# реинвестированы, налог не вычтен) и индекс гособлигаций с доходностью.
CODES = ("IMOEX", "MCFTR", "RGBI")
FIRST_DAY = date(2013, 1, 1)


def fetch(code: str, since: date) -> list[tuple]:
    """(дата, закрытие, доходность, дюрация) с `since` до сегодня."""
    rows: list[tuple] = []
    start = 0
    while True:
        try:
            response = _moex_get(
                _URL.format(code=code),
                params={"from": since.isoformat(), "start": start, "iss.meta": "off",
                        "history.columns": "TRADEDATE,CLOSE,YIELD,DURATION"},
                timeout=30,
            )
            response.raise_for_status()
            block = response.json().get("history", {})
        except Exception as exc:  # noqa: BLE001 — сеть: молча вернуть, что успели
            logger.warning("Индекс %s с %s не загрузился: %s", code, since, exc)
            break
        data = block.get("data", [])
        for day, close, yld, duration in data:
            if close is None:
                continue
            rows.append((
                date.fromisoformat(day), float(close),
                float(yld) if yld else None, int(duration) if duration else None,
            ))
        if len(data) < 100:
            break
        start += len(data)
    return rows


def store(db: Session, code: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    existing = {
        row.date: row for row in db.query(MarketIndexValue).filter(
            MarketIndexValue.code == code,
            MarketIndexValue.date.in_([r[0] for r in rows]),
        )
    }
    for day, close, yld, duration in rows:
        row = existing.get(day)
        if row is None:
            db.add(MarketIndexValue(code=code, date=day, close=close,
                                    yield_pct=yld, duration_days=duration))
        else:
            row.close, row.yield_pct, row.duration_days = close, yld, duration
    db.commit()
    return len(rows)


def refresh(db: Session, code: str) -> int:
    """Докачивает индекс с последнего известного дня (с запасом в неделю)."""
    last = db.query(func.max(MarketIndexValue.date)).filter(MarketIndexValue.code == code).scalar()
    since = FIRST_DAY if last is None else last - timedelta(days=7)
    return store(db, code, fetch(code, since))


def refresh_all(db: Session) -> int:
    total = 0
    for code in CODES:
        total += refresh(db, code)
    return total


def series(db: Session, code: str, since: Optional[date] = None) -> list[MarketIndexValue]:
    query = db.query(MarketIndexValue).filter(MarketIndexValue.code == code)
    if since is not None:
        query = query.filter(MarketIndexValue.date >= since)
    return query.order_by(MarketIndexValue.date).all()
