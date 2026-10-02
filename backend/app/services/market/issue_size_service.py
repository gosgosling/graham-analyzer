"""Выпуск акций по реестру Мосбиржи — раз в день в `companies.issue_size`.

Сам ISSUESIZE в отчёт класть нельзя: он сегодняшний (см. share_splits). Но
для текущих мультипликаторов нужен именно он — по нему видно допэмиссию или
конвертацию, случившуюся после последнего отчёта.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models.company import Company
from app.utils.moex_client import get_shares_outstanding

logger = logging.getLogger(__name__)


def refresh_all(db: Session) -> int:
    updated = 0
    for company in db.query(Company).filter(Company.ticker.isnot(None)).all():
        try:
            info = get_shares_outstanding(str(company.ticker))
        except Exception as exc:  # noqa: BLE001 — сеть: одна бумага не должна валить остальные
            logger.debug("Выпуск %s не загрузился: %s", company.ticker, exc)
            continue
        size = info.get("issuesize") if info else None
        if size:
            company.issue_size = int(size)
            company.issue_size_at = date.today()
            updated += 1
    db.commit()
    return updated
