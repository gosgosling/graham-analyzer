from sqlalchemy import ForeignKey, Integer, Numeric, DateTime, Date, String, UniqueConstraint
from datetime import datetime, date
from datetime import date as dt
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from typing import TYPE_CHECKING, Optional
from app.database import Base

if TYPE_CHECKING:
    from app.models.company import Company


class StockPrice(Base):
    """История дневных цен акции компании."""

    __tablename__ = "stock_prices"

    __table_args__ = (
        UniqueConstraint("company_id", "date", name="uq_stock_price_company_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    date: Mapped[dt] = mapped_column(Date, nullable=False, index=True)

    # Цена закрытия
    price: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)

    # Источник данных
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="tinvest"
    )  # "tinvest", "manual"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    company: Mapped["Company"] = relationship("Company", back_populates="stock_prices")
