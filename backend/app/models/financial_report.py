from sqlalchemy import ForeignKey, Integer, Numeric, DateTime, Date, String
from datetime import datetime, date
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import TYPE_CHECKING, Optional
from app.database import Base

if TYPE_CHECKING:
    from app.models.company import Company

class FinancialReport(Base):
    __tablename__ = "financial_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)

    # Relationship с Company (используем строку для избежания циклических импортов)
    company: Mapped["Company"] = relationship("Company", back_populates="reports")

    # Дата отчета (используем Date вместо DateTime для отчетности)
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Рыночные данные
    price_per_share: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # цена акции на дату отчета
    shares_outstanding: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # количество акций в обращении (исправлена опечатка)
 
    # Балансовые показатели
    total_assets: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # общие активы (Итого активы)
    total_liabilities: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # общие обязательства (Итого обяательства)
    current_assets: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # текущие активы (Итого оборотные активы)
    current_liabilities: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # текущие обязательства (Итого краткосрочные обязательства)
    equity: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # собственный капитал (Итого капитал/Итого акционерный капитал, относящийся к акционерам)

    # Отчет о прибылях и убытках
    revenue: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # выручка (Выручка от реализации)
    net_income: Mapped[Optional[float]] = mapped_column(Numeric(15, 2), nullable=True)  # чистая прибыль (Чистая прибыль)

    # Дивиденды
    dividends_per_share: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)  # дивиденды на акцию
    dividends_paid: Mapped[Optional[bool]] = mapped_column(default=False)  # выплачивались ли дивиденды в этом периоде

    # Валюта
    currency: Mapped[str] = mapped_column(String, default="RUB")  # Валюта отчета
    exchange_rate: Mapped[Optional[float]] = mapped_column(Numeric(10, 4), nullable=True)  # Курс на дату отчета

    # Метаданные
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

