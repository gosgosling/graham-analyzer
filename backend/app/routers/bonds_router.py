"""
Роутер для работы с облигациями.

Данные загружаются из T-Invest API напрямую (без сохранения в БД).
Кэш списка живёт 5 минут в памяти процесса.

Эндпоинты:
    GET /bonds/            — список российских облигаций
    GET /bonds/{figi}      — детали одной облигации по FIGI
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services.bonds.bond_service import get_bond_by_figi, get_bonds

router = APIRouter(prefix="/bonds", tags=["bonds"])


class BondResponse(BaseModel):
    figi: str
    ticker: str
    name: str
    isin: str
    currency: str
    sector: str
    country_of_risk: str
    country_of_risk_name: str
    exchange: str
    maturity_date: Optional[str]
    placement_date: Optional[str]
    nominal: Optional[float]
    coupon_quantity_per_year: Optional[int]
    floating_coupon_flag: bool
    perpetual_flag: bool
    amortization_flag: bool
    issue_size: Optional[int]
    lot: int


@router.get(
    "/",
    response_model=List[BondResponse],
    summary="Список облигаций",
    description=(
        "Возвращает список российских облигаций из T-Invest API. "
        "Результат кэшируется на 5 минут. "
        "Требуется настроенный TINKOFF_TOKEN."
    ),
)
def list_bonds():
    return get_bonds()


@router.get(
    "/{figi}",
    response_model=BondResponse,
    summary="Детали облигации",
    description="Возвращает подробную информацию об облигации по её FIGI.",
)
def get_bond(figi: str):
    bond = get_bond_by_figi(figi.upper())
    if not bond:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Облигация с FIGI '{figi}' не найдена или TINKOFF_TOKEN не настроен.",
        )
    return bond
