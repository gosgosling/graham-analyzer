from sqlalchemy import Integer, String, Boolean, DateTime, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship 
from sqlalchemy.sql import func
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from app.database import Base

if TYPE_CHECKING:
    from app.models.financial_report import FinancialReport
    from app.models.stock_price import StockPrice
    from app.models.multiplier import Multiplier

class Company(Base):
    __tablename__ = "companies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    figi: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    isin: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    sector: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="RUB")
    lot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    api_trade_available_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Год начала выплаты дивидендов (для анализа непрерывности по Грэму)
    dividend_start_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Текущая цена акции (обновляется из T-Invest API раз в день)
    current_price: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True)
    price_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Метаданные
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    reports: Mapped[List["FinancialReport"]] = relationship(
        "FinancialReport", 
        back_populates="company", 
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="FinancialReport.report_date.desc()"
    )

    stock_prices: Mapped[List["StockPrice"]] = relationship(
        "StockPrice",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="StockPrice.date.desc()",
    )

    multipliers: Mapped[List["Multiplier"]] = relationship(
        "Multiplier",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="Multiplier.date.desc()",
    )