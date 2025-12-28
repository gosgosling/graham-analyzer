from pydantic import BaseModel
from typing import Optional

class Company(BaseModel):
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
    company: Company
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

