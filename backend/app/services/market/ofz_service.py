"""Доходность 10-летних ОФЗ: загрузка кривой с Мосбиржи и ряд для оценки.

Источник — бескупонная кривая доходности ОФЗ (G-curve), эндпоинт ISS
`engines/stock/zcyc`. Кривая публикуется на каждый торговый день с января 2014
года, но за один запрос ISS отдаёт только одну дату, поэтому история грузится
по первому торговому дню месяца: оценка на графике пересчитывается раз в месяц,
и чаще ей не нужно. Текущий день докачивает ежедневный планировщик.
"""
from __future__ import annotations

import bisect
import logging
from datetime import date, timedelta
from typing import List, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from app.models.ofz_yield import OfzYield
from app.utils.moex_client import _moex_get

logger = logging.getLogger(__name__)

_URL = "https://iss.moex.com/iss/engines/stock/zcyc.json"
TERM_YEARS = 10.0
FIRST_DAY = date(2014, 1, 6)   # раньше кривая на ISS не публикуется


def fetch_on(day: date) -> Optional[Tuple[date, float]]:
    """Доходность на 10 лет на ближайший торговый день не позже `day`.

    ISS сам отдаёт последнюю кривую на дату или раньше; дата в ответе — та,
    на которую кривая действительно посчитана.
    """
    try:
        response = _moex_get(_URL, params={"date": day.isoformat(), "iss.meta": "off"}, timeout=20)
        response.raise_for_status()
        block = response.json().get("yearyields", {})
    except (requests.exceptions.RequestException, ValueError) as exc:
        logger.warning("Кривая ОФЗ на %s не загрузилась: %s", day, exc)
        return None
    cols = block.get("columns", [])
    if not cols:
        return None
    i_date, i_term, i_value = cols.index("tradedate"), cols.index("period"), cols.index("value")
    for row in block.get("data", []):
        if float(row[i_term]) == TERM_YEARS and row[i_value] is not None:
            return date.fromisoformat(row[i_date]), float(row[i_value])
    return None


def store(db: Session, rows: List[Tuple[date, float]]) -> int:
    existing = {row.date: row for row in db.query(OfzYield).filter(
        OfzYield.date.in_([day for day, _ in rows]))}
    for day, value in rows:
        if day in existing:
            existing[day].y10 = value
        else:
            db.add(OfzYield(date=day, y10=value))
    db.commit()
    return len(rows)


def load_history(db: Session, since: date = FIRST_DAY) -> int:
    """Первый торговый день каждого месяца от `since` до сегодня; пропуски докачивает."""
    have = {row[0].replace(day=1) for row in db.query(OfzYield.date)}
    cursor = date(since.year, since.month, 1)
    rows = []
    while cursor <= date.today():
        if cursor not in have:
            # Первый торговый день месяца. На выходной и праздник ISS кривую не
            # отдаёт вовсе — не «на ближайшую дату», а пусто, — поэтому дни
            # перебираются по порядку, пропуская субботы и воскресенья. Так
            # первая загрузка потеряла треть месяцев: спрашивалось седьмое
            # число, а оно то и дело выпадало на выходной.
            for offset in range(12):
                day = cursor + timedelta(days=offset)
                if day > date.today():
                    break
                if day.weekday() >= 5:
                    continue
                got = fetch_on(day)
                if got and got[0].month == cursor.month:
                    rows.append(got)
                    break
        cursor = (date(cursor.year + 1, 1, 1) if cursor.month == 12
                  else date(cursor.year, cursor.month + 1, 1))
    return store(db, rows) if rows else 0


def refresh_today(db: Session) -> int:
    got = fetch_on(date.today())
    return store(db, [got]) if got else 0


class OfzSeries:
    """Доходность ОФЗ, действовавшая на любую дату: последнее значение не позже неё."""

    def __init__(self, rows: List[Tuple[date, float]]):
        self.days = [day for day, _ in rows]
        self.values = [value for _, value in rows]

    @classmethod
    def load(cls, db: Session) -> "OfzSeries":
        rows = db.query(OfzYield.date, OfzYield.y10).order_by(OfzYield.date).all()
        return cls([(day, float(value)) for day, value in rows])

    def __bool__(self) -> bool:
        return bool(self.days)

    def on(self, day: date, max_age: int = 45) -> Optional[float]:
        """Значение не старше `max_age` дней — иначе ряда на эту дату нет."""
        i = bisect.bisect_right(self.days, day) - 1
        if i < 0 or (day - self.days[i]).days > max_age:
            return None
        return self.values[i]

    def year_average(self, year: int) -> Optional[float]:
        vals = [v for d, v in zip(self.days, self.values) if d.year == year]
        return round(sum(vals) / len(vals), 3) if vals else None
