"""Pydantic-схемы API, разложенные по сущностям.

Раньше это был один файл на 745 строк — при том что модели рядом
аккуратно разбиты по сущностям. Имена реэкспортируются, поэтому
`from app.schemas import FinancialReport` продолжает работать.
"""
from app.schemas.market import (  # noqa: F401
    Security,
    StockPriceResponse,
    PriceUpdateResponse,
)
from app.schemas.company import (  # noqa: F401
    Company,
    CompanyDescriptionUpdate,
    CompanyCreate,
    CompanyWithPrice,
)
from app.schemas.report import (  # noqa: F401
    BankMetricsOut,
    FinancialReportCreate,
    FinancialReport,
)
from app.schemas.multiplier import (  # noqa: F401
    SectorProfileOption,
    SectorProfileBand,
    SectorProfileResponse,
    MultiplierResponse,
    CurrentMultipliersResponse,
)
from app.schemas.holding import (  # noqa: F401
    CorporateDebtUpdate,
    HoldingNavOut,
    HoldingStakeIn,
    HoldingStakeOut,
    StakeValuationOut,
)
from app.schemas.dividend import (  # noqa: F401
    DividendContinuityResult,
)
from app.schemas.admin import (  # noqa: F401
    PostgresBackupResponse,
)

__all__ = [
    "BankMetricsOut",
    "CorporateDebtUpdate",
    "HoldingNavOut",
    "HoldingStakeIn",
    "HoldingStakeOut",
    "StakeValuationOut",
    "Security",
    "StockPriceResponse",
    "PriceUpdateResponse",
    "Company",
    "CompanyDescriptionUpdate",
    "CompanyCreate",
    "CompanyWithPrice",
    "FinancialReportCreate",
    "FinancialReport",
    "SectorProfileOption",
    "SectorProfileBand",
    "SectorProfileResponse",
    "MultiplierResponse",
    "CurrentMultipliersResponse",
    "DividendContinuityResult",
    "PostgresBackupResponse",
]
