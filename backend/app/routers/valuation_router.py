"""Базовый множитель рынка — данные для страницы разбора.

Эндпоинт отдаёт не одно число, а весь путь к нему: что взято из отчётов, что
выведено арифметикой, а что назначено суждением. Разделение существенно —
страница обязана показывать его явно, иначе множитель прочитается как
измерение, каковым он на две трети не является.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.market_assumption import MarketAssumption
from app.models.company import Company
from app.services.analysis import market_snapshot
from app.services.analysis.company_valuation import DEFAULT_WINDOW, assess, series
from app.services.analysis.market_multiple import (
    HISTORIC_AVERAGE,
    HISTORIC_RANGE,
    SP400_1987,
    base_multiple,
    implied_growth,
    implied_premium,
    paired_multiples,
    payout_ladder,
    sensitivity,
)

router = APIRouter(prefix="/valuation", tags=["valuation"])


def _assumption(db: Session, year: Optional[int]) -> MarketAssumption:
    query = db.query(MarketAssumption)
    row = (
        db.get(MarketAssumption, year) if year is not None
        else query.order_by(MarketAssumption.year.desc()).first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Допущений об уровне рынка нет. Задайте их командой "
                "python -m scripts.set_market_assumption"
            ),
        )
    return row


def _implied(snapshot, assumption) -> dict:
    """Что рынок закладывает в текущую цену.

    Обратный ход формулы: вместо того чтобы назначить величину и удивляться
    расхождению с ценой, спрашиваем, какое значение уже сидит в цене.
    """
    payout, multiple = snapshot.payout, snapshot.observed_multiple
    risk_free = float(assumption.risk_free_rate)
    premium = float(assumption.risk_premium)
    growth = float(assumption.dividend_growth)

    # Третий разворот: какую долгосрочную ставку подразумевает цена, если
    # премия и рост приняты. Считается прямо здесь — отдельная функция ради
    # одного вычитания не нужна.
    implied_rate = None
    if payout and multiple:
        implied_rate = round(payout / multiple + growth - premium, 2)

    return {
        "growth_at_stated_premium": implied_growth(payout, risk_free, premium, multiple),
        "premium_at_stated_growth": implied_premium(payout, risk_free, growth, multiple),
        "risk_free_at_stated_premium_and_growth": implied_rate,
    }


@router.get("/market-multiple")
def market_multiple(
    year: Optional[int] = Query(None, description="год допущений; по умолчанию последний"),
    data_year: int = Query(market_snapshot.DEFAULT_YEAR, description="год данных о выплате"),
    db: Session = Depends(get_db),
) -> dict:
    assumption = _assumption(db, year)
    snapshot = market_snapshot.snapshot(db, data_year)

    payout = (
        float(assumption.payout) if assumption.payout is not None else snapshot.payout
    )
    normalized = (
        float(assumption.normalized_risk_free_rate)
        if assumption.normalized_risk_free_rate is not None else None
    )
    pair = paired_multiples(
        payout,
        float(assumption.risk_free_rate),
        float(assumption.risk_premium),
        float(assumption.dividend_growth),
        normalized,
    )

    return {
        "assumption": {
            "year": assumption.year,
            "risk_free_rate": float(assumption.risk_free_rate),
            "normalized_risk_free_rate": normalized,
            "risk_premium": float(assumption.risk_premium),
            "dividend_growth": float(assumption.dividend_growth),
            "payout": float(assumption.payout) if assumption.payout is not None else None,
            "payout_used": payout,
            "payout_from_data": assumption.payout is None,
            "note": assumption.note,
            "source": assumption.source,
        },
        "snapshot": snapshot.as_dict(),
        "current": pair["current"].as_dict() if pair["current"] else None,
        "normalized": pair["normalized"].as_dict() if pair["normalized"] else None,
        "rate_effect": pair["rate_effect"],
        "sensitivity": sensitivity(pair["current"]) if pair["current"] else [],
        # Лестница выплаты: рост на каждой ступени свой, потому что расти
        # можно только на то, что не раздал.
        "payout_ladder": payout_ladder(
            snapshot.roe,
            float(assumption.risk_free_rate),
            float(assumption.risk_premium),
            normalized,
        ),
        "implied": _implied(snapshot, assumption),
        "reference": {
            "book": SP400_1987,
            "book_multiple": base_multiple(**SP400_1987).value,
            "historic_average": HISTORIC_AVERAGE,
            "historic_range": list(HISTORIC_RANGE),
        },
    }


@router.get("/company/{company_id}")
def company_valuation(
    company_id: int,
    window: int = Query(DEFAULT_WINDOW, ge=3, le=15, description="окно нормализации, лет"),
    year: Optional[int] = Query(None, description="год допущений; по умолчанию последний"),
    db: Session = Depends(get_db),
) -> dict:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return assess(db, company, _assumption(db, year), window)


@router.get("/company/{company_id}/series")
def company_series(
    company_id: int,
    window: int = Query(DEFAULT_WINDOW, ge=3, le=15, description="окно нормализации, лет"),
    db: Session = Depends(get_db),
) -> dict:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return series(db, company, window)
