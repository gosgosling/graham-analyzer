"""Схемы мультипликаторов и отраслевых профилей."""
from datetime import date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Multiplier schemas
# ---------------------------------------------------------------------------

class SectorProfileOption(BaseModel):
    """Элемент списка профилей для выбора аналитиком в карточке компании."""
    key: str
    label: str
    summary: str


class SectorProfileBand(BaseModel):
    """Пороги одной метрики в рамках отраслевого профиля."""
    good: Optional[float] = None
    warn: Optional[float] = None
    higher_is_better: bool
    hint: str
    applicable: bool = True
    note: Optional[str] = None
    tooltip_lines: List[str] = []


class SectorProfileResponse(BaseModel):
    """
    Отраслевой профиль порогов. Определяется на бэкенде по сектору компании
    и типу отчёта; фронтенд раскрашивает карточки и таблицу по этим значениям,
    чтобы пороги не расходились между слоями.
    """
    key: str
    label: str
    summary: str
    book_value_reliable: bool = True
    lease_heavy: bool = False
    bands: Dict[str, SectorProfileBand]


class MultiplierResponse(BaseModel):
    """Схема ответа для кэшированных мультипликаторов."""
    id: int
    company_id: int
    report_id: Optional[int] = None
    date: date
    type: str

    # Рыночные данные
    price_used: Optional[float] = None
    shares_used: Optional[int] = None
    shares_issued: Optional[int] = None
    shares_outstanding_circulation: Optional[int] = None
    shares_cap_explanation: Optional[str] = None
    market_cap: Optional[float] = None

    # LTM P&L
    ltm_net_income: Optional[float] = None
    ltm_revenue: Optional[float] = None
    ltm_dividends_per_share: Optional[float] = None
    ltm_special_dividends_per_share: Optional[float] = None  # разовая часть, ₽/акцию

    # Балансовые данные
    equity: Optional[float] = None
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None

    # Мультипликаторы
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    pb_tangible: Optional[float] = None       # P/B без гудвила
    goodwill: Optional[float] = None          # млн ₽
    goodwill_to_assets: Optional[float] = None  # %
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_yield_regular: Optional[float] = None  # без разовых выплат
    cost_to_income: Optional[float] = None  # % — только для банков
    # Гибрид (операционка + встроенный банк): приток от роста банковского
    # баланса и свободный поток без него. У остальных типов — null.
    banking_flow: Optional[float] = None      # млн ₽, прирост депозитов − прирост кредитов
    ltm_core_fcf: Optional[float] = None      # млн ₽, FCF ядра
    banking_flow_basis: Optional[str] = None  # 'cash_flow' | 'balance_delta'
    # По какому потоку посчитаны P/FCF, ND/FCF и FCF/NI: 'core' | 'reported'
    fcf_basis: Optional[str] = None

    # Денежные потоки LTM (NULL для банков)
    ltm_fcf: Optional[float] = None
    ltm_operating_cash_flow: Optional[float] = None
    ltm_capex: Optional[float] = None
    # Мультипликаторы FCF (NULL для банков)
    price_to_fcf: Optional[float] = None
    fcf_to_net_income: Optional[float] = None  # FCF/NI, безразмерное соотношение
    eps: Optional[float] = None  # Прибыль на акцию, ₽ (от тех же акций, что и капитализация)
    net_debt: Optional[float] = None  # млн ₽
    net_debt_to_fcf: Optional[float] = None  # Net Debt / LTM FCF

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Из связанного отчёта: дата публикации и цена на эту дату (в ₽), для подсказки в UI
    filing_date: Optional[date] = None
    price_at_filing_rub: Optional[float] = None

    class Config:
        from_attributes = True


class CurrentMultipliersResponse(BaseModel):
    """Схема ответа для «живых» актуальных мультипликаторов (вычисляются на лету)."""
    company_id: int
    date: str
    current_price: Optional[float] = None
    balance_report_id: Optional[int] = None
    balance_report_date: Optional[str] = None
    ltm_source: Optional[str] = None

    # LTM P&L
    ltm_net_income: Optional[float] = None
    ltm_revenue: Optional[float] = None
    ltm_dividends_per_share: Optional[float] = None
    ltm_special_dividends_per_share: Optional[float] = None  # разовая часть, ₽/акцию

    # Расчётные данные
    price_used: Optional[float] = None
    shares_used: Optional[int] = None
    shares_issued: Optional[int] = None
    shares_outstanding_circulation: Optional[int] = None
    shares_cap_explanation: Optional[str] = None
    market_cap: Optional[float] = None
    equity: Optional[float] = None  # собственный капитал, млн ₽ (из балансового отчёта)
    total_assets: Optional[float] = None  # итого активы, млн ₽ (для разложения ROE)

    # Отраслевой профиль порогов, применённый к этой компании
    sector_profile: Optional[SectorProfileResponse] = None

    # Мультипликаторы
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    pb_tangible: Optional[float] = None       # P/B без гудвила
    goodwill: Optional[float] = None          # млн ₽
    goodwill_to_assets: Optional[float] = None  # %
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    dividend_yield: Optional[float] = None
    dividend_yield_regular: Optional[float] = None  # без разовых выплат
    cost_to_income: Optional[float] = None  # % — только для банков
    # Гибрид (операционка + встроенный банк): приток от роста банковского
    # баланса и свободный поток без него. У остальных типов — null.
    banking_flow: Optional[float] = None      # млн ₽, прирост депозитов − прирост кредитов
    ltm_core_fcf: Optional[float] = None      # млн ₽, FCF ядра
    banking_flow_basis: Optional[str] = None  # 'cash_flow' | 'balance_delta'
    # По какому потоку посчитаны P/FCF, ND/FCF и FCF/NI: 'core' | 'reported'
    fcf_basis: Optional[str] = None

    # Денежные потоки LTM (NULL для банков)
    ltm_fcf: Optional[float] = None
    ltm_operating_cash_flow: Optional[float] = None
    ltm_capex: Optional[float] = None
    # Мультипликаторы FCF (NULL для банков)
    price_to_fcf: Optional[float] = None
    fcf_to_net_income: Optional[float] = None  # FCF/NI, безразмерное соотношение
    eps: Optional[float] = None  # Прибыль на акцию, ₽ (от тех же акций, что и капитализация)
    net_debt: Optional[float] = None  # млн ₽
    net_debt_to_fcf: Optional[float] = None  # Net Debt / LTM FCF
