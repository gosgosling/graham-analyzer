"""Схемы рыночных данных: бумаги MOEX, цены."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class Security(BaseModel):
    secid: str
    boardid: str
    shortname: str
    prevprice: Optional[float] = None
    lotsize: int
    facevalue: float
    status: str
    boardname: str
    decimals: int
    secname: str
    remarks: Optional[str] = None
    marketcode: str
    instrid: str
    sectorid: Optional[str] = None
    minstep: float
    prevwaprice: Optional[float] = None
    faceunit: str
    prevdate: Optional[str] = None  # Будет строка из API
    issuesize: int
    isin: str
    latname: str
    regnumber: Optional[str] = None
    prevlegalcloseprice: Optional[float] = None
    currencyid: str
    sectype: str
    listlevel: int
    settledate: Optional[str] = None  # Будет строка из API


# ---------------------------------------------------------------------------
# StockPrice schemas
# ---------------------------------------------------------------------------

class StockPriceResponse(BaseModel):
    """Схема ответа для записи исторической цены акции."""
    id: int
    company_id: int
    date: date
    price: float
    source: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PriceUpdateResponse(BaseModel):
    """Ответ при обновлении цены компании."""
    company_id: int
    ticker: str
    figi: str
    price: Optional[float]
    updated_at: Optional[datetime] = None
    success: bool
