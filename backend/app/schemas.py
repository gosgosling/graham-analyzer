from pydantic import BaseModel
from typing import Optional

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

class Multipliers(BaseModel):
    company_id: int
    pe_ratio: float
    pb_ratio: float
    debt_to_equity: float
    roe: float
    dividend_yield: float
    date: str

class AnalysisItem(BaseModel):
    security: Security
    multipliers: Multipliers
    category: str

class AnalysisResponse(BaseModel):
    undervalued: list[AnalysisItem]
    stable: list[AnalysisItem]
    overvalued: list[AnalysisItem]

class CompanyResult(BaseModel):
    company_id: int
    company_name: str
    category: str
    multipliers: Multipliers
    analysis: dict
    recommendation: str
    date: str


class AnalysisDetails(BaseModel):
    pe_ratio_status: str
    pb_ratio_status: str
    debt_status: str
    liquidity_status: str
    profitability_status: str

class Company(BaseModel):
    """Схема для компании из Tinkoff Invest API"""
    figi: str  # FIGI - уникальный идентификатор инструмента
    ticker: str  # Тикер
    name: str  # Название компании
    isin: Optional[str] = None  # ISIN для связи с MOEX
    sector: Optional[str] = None  # Сектор
    currency: str  # Валюта
    lot: int  # Размер лота
    api_trade_available_flag: bool = False  # Доступность для торговли через API


class CompanyCreate(BaseModel):
    figi: str
    ticker: str
    name: str
    isin: Optional[str] = None
    sector: Optional[str] = None
    currency: str = "RUB"
    lot: int = 1
    api_trade_available_flag: bool = False