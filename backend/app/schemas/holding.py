"""Схемы оценки холдинга: доли и NAV."""
from typing import List, Optional

from pydantic import BaseModel


class HoldingStakeIn(BaseModel):
    """Доля холдинга. Либо ссылка на карточку дочки, либо ручная оценка."""

    name: str
    share_pct: float
    subsidiary_company_id: Optional[int] = None
    # Стоимость ВСЕЙ дочки, млн ₽ — для непубличных активов
    manual_valuation: Optional[float] = None
    valuation_note: Optional[str] = None


class HoldingStakeOut(HoldingStakeIn):
    id: int

    class Config:
        from_attributes = True


class StakeValuationOut(BaseModel):
    """Доля с посчитанной стоимостью."""

    stake_id: int
    name: str
    ticker: Optional[str] = None
    subsidiary_company_id: Optional[int] = None
    share_pct: float
    company_value: Optional[float] = None   # стоимость всей дочки, млн ₽
    stake_value: Optional[float] = None     # стоимость доли, млн ₽
    source: str                             # market | manual | unknown
    missing: Optional[str] = None           # чего не хватает для оценки


class HoldingNavOut(BaseModel):
    """Итог оценки холдинга.

    `valued_stakes` из `total_stakes` показывает полноту расчёта: пока
    карточки дочек не дозаполнены, часть долей оценить нечем, и NAV
    занижен — об этом интерфейс обязан сказать прямо.
    """

    company_id: int
    stakes: List[StakeValuationOut] = []
    stakes_value: Optional[float] = None
    corporate_center_net_debt: Optional[float] = None
    nav: Optional[float] = None
    market_cap: Optional[float] = None
    discount_pct: Optional[float] = None
    valued_stakes: int = 0
    total_stakes: int = 0


class CorporateDebtUpdate(BaseModel):
    """Тело PATCH: чистый долг корпоративного центра, млн ₽."""

    corporate_center_net_debt: Optional[float] = None
