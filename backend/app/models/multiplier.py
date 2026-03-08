from sqlalchemy import ForeignKey, Integer, BigInteger, Numeric, DateTime, Date, String, UniqueConstraint
from datetime import datetime, date
from datetime import date as dt
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import TYPE_CHECKING, Optional
from app.database import Base

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.financial_report import FinancialReport


class Multiplier(Base):
    """
    Кэш рассчитанных мультипликаторов.

    Типы записей (поле `type`):
    - "report_based" — рассчитан на дату отчёта, цена из самого отчёта
    - "current"      — рассчитан на сегодня по текущей рыночной цене
    - "daily"        — ежедневный расчёт по историческим ценам
    """

    __tablename__ = "multipliers"

    __table_args__ = (
        UniqueConstraint("company_id", "date", "type", name="uq_multiplier_company_date_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Ссылка на отчёт, из которого взяты балансовые данные
    report_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("financial_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )

    date: Mapped[dt] = mapped_column(Date, nullable=False, index=True)

    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="current"
    )  # "report_based" | "current" | "daily"

    # Рыночные данные, использованные при расчёте
    price_used: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True)
    shares_used: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    market_cap: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)

    # LTM показатели P&L (Last Twelve Months)
    ltm_net_income: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    ltm_revenue: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    ltm_dividends_per_share: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True)

    # Балансовые данные из последнего отчёта
    equity: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    total_liabilities: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    current_assets: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)
    current_liabilities: Mapped[Optional[float]] = mapped_column(Numeric(20, 2), nullable=True)

    # Рассчитанные мультипликаторы
    pe_ratio: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    pb_ratio: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    roe: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    debt_to_equity: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    current_ratio: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    dividend_yield: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    company: Mapped["Company"] = relationship("Company", back_populates="multipliers")
    report: Mapped[Optional["FinancialReport"]] = relationship(
        "FinancialReport", back_populates="multipliers"
    )
