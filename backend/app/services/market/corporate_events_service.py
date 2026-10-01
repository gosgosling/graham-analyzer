"""Дивидендные отсечки и сплиты — для засечек на графике цены.

Дивиденды — T-Invest, `InstrumentsService/GetDividends`: дата реестра,
последний день покупки с дивидендом, сумма на акцию. Открытый эндпоинт
Мосбиржи `/securities/{тикер}/dividends.json` в 2026 году отдаёт описание
бумаги вместо выплат — и вместе с ним молча перестал работать
`moex_client.get_dividends_for_period`.

Сплиты — Мосбиржа, `/statistics/engines/stock/splits.json`, одним запросом на
всю биржу.

Хранится у себя (`corporate_events`): график не должен зависеть от того,
отвечают ли биржа и брокер, а обновление раз в день — дёшево.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Company
from app.models.corporate_event import CorporateEvent
from app.utils.moex_client import _moex_get
from app.utils.tinkoff_client import external_session

logger = logging.getLogger(__name__)

ISS = "https://iss.moex.com/iss"


def _table(payload: dict, name: str) -> list[dict]:
    block = payload.get(name) or {}
    columns = block.get("columns") or []
    return [dict(zip(columns, row)) for row in block.get("data") or []]


DIVIDENDS_FROM = 2010  # история цен в базе начинается с 2010 года

TINVEST_DIVIDENDS = (
    "https://invest-public-api.tinkoff.ru/rest/"
    "tinkoff.public.invest.api.contract.v1.InstrumentsService/GetDividends"
)


def _money(value: Optional[dict]) -> Optional[float]:
    """Quotation T-Invest → число: целая часть и миллиардные доли."""
    if not value:
        return None
    try:
        return int(value.get("units") or 0) + int(value.get("nano") or 0) / 1e9
    except (TypeError, ValueError):
        return None


def _day(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def fetch_dividends(figi: str) -> Optional[list[tuple]]:
    """[(дата реестра, последний день покупки, сумма, валюта)] или None при сбое."""
    from app.config import settings

    token = (settings.TINKOFF_TOKEN or "").strip()
    if not figi or not token or token == "your_token_here":
        return None
    try:
        resp = external_session().post(
            TINVEST_DIVIDENDS,
            # Диапазон ограничен: на «2000–2100» T-Invest отвечает 400.
            json={"figi": figi, "from": f"{DIVIDENDS_FROM}-01-01T00:00:00Z",
                  "to": f"{date.today().year + 2}-12-31T00:00:00Z"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json().get("dividends") or []
    except Exception as exc:  # noqa: BLE001 — сеть, JSON, что угодно: пропускаем бумагу
        logger.warning("Дивиденды %s из T-Invest не получены: %s", figi, exc)
        return None
    # Одна и та же выплата бывает в ответе дважды (ЛУКОЙЛ, реестр 21.12.2022).
    # Ответ идёт от свежих записей к старым — остаётся первая, то есть
    # последняя по времени правка.
    seen: dict[date, tuple] = {}
    for row in rows:
        record, net = _day(row.get("recordDate")), row.get("dividendNet") or {}
        value = _money(net)
        if record is None or value is None or value <= 0 or record in seen:
            continue
        seen[record] = (record, _day(row.get("lastBuyDate")), value,
                        str(net.get("currency") or "rub").upper())
    return list(seen.values())


def fetch_splits() -> Optional[dict[str, list[tuple]]]:
    """{тикер: [(дата, коэффициент после ÷ до)]} по всей бирже."""
    try:
        resp = _moex_get(f"{ISS}/statistics/engines/stock/splits.json",
                         params={"iss.meta": "off"}, timeout=15)
        resp.raise_for_status()
        rows = _table(resp.json(), "splits")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Сплиты с Мосбиржи не получены: %s", exc)
        return None
    out: dict[str, list[tuple]] = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["tradedate"])
            ratio = float(row["after"]) / float(row["before"])
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        out.setdefault(str(row.get("secid")), []).append((day, ratio))
    return out


def _upsert(db: Session, company_id: int, kind: str, day: date,
            value: Optional[float], currency: Optional[str],
            last_buy: Optional[date] = None) -> bool:
    """Вставляет событие или обновляет сумму. → True, если что-то изменилось."""
    row = (
        db.query(CorporateEvent)
        .filter(CorporateEvent.company_id == company_id,
                CorporateEvent.kind == kind, CorporateEvent.date == day)
        .first()
    )
    if row is None:
        db.add(CorporateEvent(company_id=company_id, kind=kind, date=day,
                              value=value, currency=currency, last_buy_date=last_buy))
        db.flush()  # следующий поиск должен видеть эту строку
        return True
    changed = False
    if value is not None and (row.value is None or abs(float(row.value) - value) > 1e-9):
        row.value = value
        changed = True
    if last_buy is not None and row.last_buy_date != last_buy:
        row.last_buy_date = last_buy
        changed = True
    return changed


def refresh_company(db: Session, company: Company,
                    splits: Optional[dict[str, list[tuple]]] = None) -> int:
    """Обновляет события одной компании. → сколько строк добавлено или изменено."""
    changed = 0
    for day, last_buy, value, currency in fetch_dividends(company.figi) or []:
        changed += _upsert(db, company.id, "dividend", day, value, currency, last_buy)
    for day, ratio in (splits or {}).get(company.ticker, []):
        changed += _upsert(db, company.id, "split", day, ratio, None)
    db.commit()
    return changed


def refresh_all(db: Session) -> int:
    """Все компании базы. Сплиты запрашиваются один раз на весь обход."""
    splits = fetch_splits() or {}
    total = 0
    for company in db.query(Company).order_by(Company.ticker).all():
        if not company.ticker:
            continue
        try:
            total += refresh_company(db, company, splits)
        except Exception as exc:  # noqa: BLE001 — одна бумага не должна ронять обход
            db.rollback()
            logger.warning("События %s не обновлены: %s", company.ticker, exc)
    return total
