"""Доли холдинга и оценка по NAV.

Холдинг оценивается суммой долей за вычетом долга корпоративного центра —
консолидированные мультипликаторы показывают бизнес дочек, а не стоимость
для акционера. Доли ведёт аналитик руками: доля владения в отчётности не
раскрывается в пригодном для расчёта виде, а непубличные активы вообще
требуют экспертной оценки.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.holding_stake import HoldingStake
from app.schemas import (
    CorporateDebtUpdate,
    HoldingNavOut,
    HoldingStakeIn,
    HoldingStakeOut,
)
from app.services.holdings.nav_service import compute_holding_nav

router = APIRouter(prefix="/companies/{company_id}/holding", tags=["holdings"])


def _get_company(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return company


def _validate(db: Session, payload: HoldingStakeIn) -> None:
    if not 0 < payload.share_pct <= 100:
        raise HTTPException(
            status_code=422, detail="Доля владения должна быть в диапазоне (0; 100]"
        )
    if payload.subsidiary_company_id is None and payload.manual_valuation is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Нужна либо ссылка на карточку дочки, либо ручная оценка её "
                "стоимости: иначе долю нечем оценить"
            ),
        )
    if payload.subsidiary_company_id is not None:
        _get_company(db, payload.subsidiary_company_id)


@router.get("/nav", response_model=HoldingNavOut)
def get_holding_nav(company_id: int, db: Session = Depends(get_db)):
    """NAV, дисконт и разбор по долям.

    Незаполненные карточки дочек не обнуляют долю: она попадает в список
    неоценённых, а полнота расчёта видна по `valued_stakes` из `total_stakes`.
    """
    nav = compute_holding_nav(db, company_id)
    if nav is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return nav


@router.get("/stakes", response_model=List[HoldingStakeOut])
def list_stakes(company_id: int, db: Session = Depends(get_db)):
    _get_company(db, company_id)
    return (
        db.query(HoldingStake)
        .filter(HoldingStake.holding_company_id == company_id)
        .order_by(HoldingStake.id)
        .all()
    )


@router.post("/stakes", response_model=HoldingStakeOut, status_code=status.HTTP_201_CREATED)
def add_stake(company_id: int, payload: HoldingStakeIn, db: Session = Depends(get_db)):
    _get_company(db, company_id)
    _validate(db, payload)

    stake = HoldingStake(holding_company_id=company_id, **payload.model_dump())
    db.add(stake)
    db.commit()
    db.refresh(stake)
    return stake


@router.put("/stakes/{stake_id}", response_model=HoldingStakeOut)
def update_stake(
    company_id: int, stake_id: int, payload: HoldingStakeIn, db: Session = Depends(get_db)
):
    _validate(db, payload)
    stake = (
        db.query(HoldingStake)
        .filter(HoldingStake.id == stake_id, HoldingStake.holding_company_id == company_id)
        .first()
    )
    if stake is None:
        raise HTTPException(status_code=404, detail="Доля не найдена")

    for field, value in payload.model_dump().items():
        setattr(stake, field, value)
    db.commit()
    db.refresh(stake)
    return stake


@router.delete("/stakes/{stake_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stake(company_id: int, stake_id: int, db: Session = Depends(get_db)):
    stake = (
        db.query(HoldingStake)
        .filter(HoldingStake.id == stake_id, HoldingStake.holding_company_id == company_id)
        .first()
    )
    if stake is None:
        raise HTTPException(status_code=404, detail="Доля не найдена")
    db.delete(stake)
    db.commit()


@router.patch("/corporate-debt", response_model=HoldingNavOut)
def set_corporate_debt(
    company_id: int, payload: CorporateDebtUpdate, db: Session = Depends(get_db)
):
    """Чистый долг корпоративного центра, млн ₽.

    В консолидированной отчётности он не выделен — там долг всех дочек
    вместе, — поэтому берётся из презентаций эмитента и обновляется руками.
    """
    company = _get_company(db, company_id)
    company.corporate_center_net_debt = payload.corporate_center_net_debt  # type: ignore[assignment]
    db.commit()
    return compute_holding_nav(db, company_id)
