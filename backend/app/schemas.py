from pydantic import BaseModel

class Company(BaseModel):
    id: int 
    name: str
    ticker: str
    sector: str
    industry: str

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




