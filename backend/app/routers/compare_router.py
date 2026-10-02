"""Сравнение компаний одной отрасли (гл. 18 «Разумного инвестора»)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.services.analysis import compare

router = APIRouter(prefix="/compare", tags=["compare"])


def _summary(db: Session):
    from app.routers.valuation_router import DEFAULT_WINDOW, company_summary

    return lambda company_id: company_summary(company_id=company_id, window=DEFAULT_WINDOW, db=db)


@router.get("")
def compare_companies(
    ids: Optional[str] = Query(None, description="id компаний через запятую, до пяти"),
    with_id: Optional[int] = Query(None, alias="with", description="компания + крупнейшие соседи по отрасли"),
    all_peers: bool = Query(False, alias="all", description="вся отрасль компании `with`"),
    db: Session = Depends(get_db),
) -> dict:
    """Таблица сравнения и комментарий, собранный по правилам из её чисел.

    Либо явный список `ids` (2–5 компаний), либо `with` — компания и три
    крупнейшие соседки по отрасли; `all=1` — вся отрасль.
    """
    companies: list[Company] = []
    if ids:
        try:
            wanted = [int(x) for x in ids.split(",") if x.strip()][: compare.MAX_PICK]
        except ValueError:
            raise HTTPException(status_code=400, detail="ids — числа через запятую")
        found = {c.id: c for c in db.query(Company).filter(Company.id.in_(wanted))}
        companies = [found[i] for i in wanted if i in found]
    elif with_id is not None:
        anchor = db.get(Company, with_id)
        if anchor is None:
            raise HTTPException(status_code=404, detail="Компания не найдена")
        group = compare.peers(db, anchor)
        others = [c for c in group if c.id != anchor.id]
        companies = [anchor] + (others if all_peers else others[: compare.MAX_PICK - 2])
    if not companies:
        raise HTTPException(status_code=400, detail="Укажите компании: ids или with")
    return compare.build(db, companies, _summary(db))


@router.get("/peers/{company_id}")
def company_peers(company_id: int, db: Session = Depends(get_db)) -> dict:
    """Проверенные компании той же отрасли, крупные первыми."""
    anchor = db.get(Company, company_id)
    if anchor is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    key = compare.group_key(db, anchor)
    return {
        "group": compare.group_label(key),
        "companies": [{"id": c.id, "ticker": c.ticker, "name": c.name} for c in compare.peers(db, anchor)],
    }


@router.get("/groups")
def compare_groups(db: Session = Depends(get_db)) -> list[dict]:
    """Отрасли проверенных компаний — с чего начать сравнение во вкладке
    скринера. Компании в отрасли — крупные первыми."""
    from app.services.analysis.market_snapshot import trustworthy_tickers

    groups: dict = {}
    for ticker in trustworthy_tickers(db):
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if company is not None:
            groups.setdefault(compare.group_key(db, company), []).append(company)
    out = []
    for key, members in groups.items():
        members.sort(key=lambda c: -(compare._market_cap(db, c) or 0))
        out.append({
            "label": compare.group_label(key),
            "companies": [{"id": c.id, "ticker": c.ticker, "name": c.name} for c in members],
        })
    return sorted(out, key=lambda g: -len(g["companies"]))
