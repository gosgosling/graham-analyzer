from sqlalchemy import ForeignKey, Integer, BigInteger, Numeric, DateTime, Date, String, Enum as SQLEnum, UniqueConstraint
from datetime import datetime, date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import TYPE_CHECKING, Optional, List
from app.database import Base
from app.models.enums import PeriodType, AccountingStandard, ReportSource

if TYPE_CHECKING:
    from app.models.company import Company
    from app.models.multiplier import Multiplier

class FinancialReport(Base):
    __tablename__ = "financial_reports"
    
    # Уникальный constraint для предотвращения дублирования
    __table_args__ = (
        UniqueConstraint(
            'company_id', 'fiscal_year', 'fiscal_quarter', 
            'period_type', 'accounting_standard', 'consolidated',
            name='uq_financial_report'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)

    company: Mapped["Company"] = relationship("Company", back_populates="reports")

    multipliers: Mapped[List["Multiplier"]] = relationship(
        "Multiplier",
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    # Атрибуты отчёта
    period_type: Mapped[str] = mapped_column(
        SQLEnum(PeriodType, native_enum=False, length=20),
        nullable=False,
        default=PeriodType.QUARTERLY,
        index=True
    )  # Тип периода: квартальный/годовой/полугодовой
    
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # Финансовый год отчёта
    fiscal_quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Квартал (1-4), NULL для годовых
    
    accounting_standard: Mapped[str] = mapped_column(
        SQLEnum(AccountingStandard, native_enum=False, length=20),
        nullable=False,
        default=AccountingStandard.IFRS,
        index=True
    )  # Стандарт отчётности (МСФО, РСБУ, US GAAP...)
    
    consolidated: Mapped[bool] = mapped_column(default=True, nullable=False)  # Консолидированная отчётность?
    
    # Даты
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # Дата окончания отчётного периода
    filing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # Дата публикации отчёта
    
    source: Mapped[str] = mapped_column(
        SQLEnum(ReportSource, native_enum=False, length=30),
        nullable=False,
        default=ReportSource.MANUAL
    )  # Источник данных

    # Рыночные данные
    # price_per_share и dividends_per_share — в ПОЛНЫХ единицах валюты (рублях/долларах за акцию)
    # shares_outstanding — полное количество акций
    price_per_share: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True)  # Цена акции на report_date (₽ или $ за акцию)
    price_at_filing: Mapped[Optional[float]] = mapped_column(Numeric(15, 4), nullable=True)  # Цена акции на filing_date (₽ или $ за акцию)
    shares_outstanding: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)  # Количество акций в обращении (штук)

    # ⚠️ ЕДИНИЦЫ ХРАНЕНИЯ: все финансовые показатели ниже — в МИЛЛИОНАХ валюты отчёта (млн ₽ или млн $)
    # Пример: выручка 1 459 000 млн ₽ → вводить 1459000

    # Балансовые показатели (млн валюты)
    total_assets: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Итого активы, млн
    total_liabilities: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Итого обязательства, млн
    current_assets: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Итого оборотные активы, млн
    current_liabilities: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Итого краткосрочные обязательства, млн
    equity: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Итого собственный капитал, млн

    # Отчёт о прибылях и убытках (млн валюты)
    revenue: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Выручка, млн
    net_income: Mapped[Optional[float]] = mapped_column(Numeric(15, 3), nullable=True)  # Чистая прибыль, млн
    net_income_reported: Mapped[Optional[float]] = mapped_column(
        Numeric(15, 3), nullable=True
    )  # Фактическая (отчётная) прибыль по раскрытию, млн — если отличается от net_income

    # Дивиденды
    dividends_per_share: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)  # Дивиденды на акцию (₽ или $ за акцию)
    dividends_paid: Mapped[Optional[bool]] = mapped_column(default=False)  # выплачивались ли дивиденды в этом периоде

    # Валюта
    currency: Mapped[str] = mapped_column(String, default="RUB")  # Валюта отчета
    exchange_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)  # Курс на дату отчета

    # Метаданные
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

