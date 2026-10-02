"""Нефть Brent и курс доллара — для графика цены у нефтяных компаний.

Хранятся в той же таблице, что индексы Мосбиржи (`market_index_values`),
под кодами BRENT ($/барр.) и USDRUB (₽ за доллар):

* Brent — дневная цена Europe Brent Spot из FRED (ряд DCOILBRENTEU). Это
  открытый CSV без ключа, ряд с 1987 года.
* Курс — официальный курс ЦБ (динамика по дням, R01235).

Urals здесь нет: Минфин публикует его среднемесячную цену только текстом,
машиночитаемого ряда нет. Поэтому на графике Urals — это Brent минус
дисконт, который читатель задаёт сам.
"""
from __future__ import annotations

import csv
import io
import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.market_index import MarketIndexValue
from app.services.market.index_service import store
from app.utils.moex_client import _moex_get

logger = logging.getLogger(__name__)

BRENT, USDRUB = "BRENT", "USDRUB"
FIRST_DAY = date(2013, 1, 1)
_FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_CBR = "https://www.cbr.ru/scripts/XML_dynamic.asp"


def fetch_brent(since: date) -> list[tuple]:
    try:
        response = _moex_get(_FRED, params={"id": "DCOILBRENTEU", "cosd": since.isoformat()}, timeout=30)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — сеть
        logger.warning("Brent с FRED не загрузился: %s", exc)
        return []
    rows = []
    for line in csv.reader(io.StringIO(response.text)):
        if len(line) != 2 or not line[1] or line[1] == "." or not line[0][:1].isdigit():
            continue
        day = date.fromisoformat(line[0])
        if day >= since:
            rows.append((day, float(line[1]), None, None))
    return rows


def fetch_usdrub(since: date, till: Optional[date] = None) -> list[tuple]:
    till = till or date.today()
    try:
        response = _moex_get(_CBR, params={
            "date_req1": since.strftime("%d/%m/%Y"), "date_req2": till.strftime("%d/%m/%Y"),
            "VAL_NM_RQ": "R01235",
        }, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:  # noqa: BLE001 — сеть
        logger.warning("Курс доллара ЦБ не загрузился: %s", exc)
        return []
    rows = []
    for record in root.findall("Record"):
        day = date(*reversed([int(x) for x in record.attrib["Date"].split(".")]))
        nominal = float(record.findtext("Nominal", "1").replace(",", "."))
        value = float(record.findtext("Value", "0").replace(",", "."))
        rows.append((day, value / nominal, None, None))
    return rows


def refresh(db: Session) -> int:
    """Докачать оба ряда с последнего дня (с запасом в неделю)."""
    total = 0
    for code, fetch in ((BRENT, fetch_brent), (USDRUB, fetch_usdrub)):
        last = db.query(func.max(MarketIndexValue.date)).filter(MarketIndexValue.code == code).scalar()
        since = FIRST_DAY if last is None else last - timedelta(days=7)
        total += store(db, code, fetch(since))
    return total


def oil_series(db: Session, since: Optional[date] = None) -> list[tuple[date, float, Optional[float]]]:
    """(дата, Brent $, курс ₽/$) по дням Brent. Курс — последний известный
    на эту дату: ЦБ по выходным не устанавливает, а Brent в праздники РФ есть."""
    def load(code):
        q = db.query(MarketIndexValue.date, MarketIndexValue.close).filter(MarketIndexValue.code == code)
        if since is not None:
            # Курс берём с запасом назад, чтобы у первого дня Brent он был.
            q = q.filter(MarketIndexValue.date >= (since - timedelta(days=14) if code == USDRUB else since))
        return [(d, float(v)) for d, v in q.order_by(MarketIndexValue.date)]

    brent, fx = load(BRENT), load(USDRUB)
    out, j, rate = [], 0, None
    for day, price in brent:
        while j < len(fx) and fx[j][0] <= day:
            rate = fx[j][1]
            j += 1
        out.append((day, price, rate))
    return out
