"""События по бумаге, которые рынок видит на графике: дивидендные отсечки и сплиты.

Дивиденды — из T-Invest (`GetDividends`): открытый эндпоинт дивидендов
Мосбиржи в 2026 году отдаёт описание бумаги вместо выплат. Сплиты — Мосбиржа.

Хранятся у себя, как и цены: график не должен зависеть от того, отвечает ли
сегодня биржа или брокер. Выход отчётов сюда не пишется — он уже есть в
`financial_reports.disclosed_at`, и второй копии незачем расходиться с первой.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class CorporateEvent(Base):
    __tablename__ = "corporate_events"
    __table_args__ = (
        UniqueConstraint("company_id", "kind", "date", name="uq_corporate_event"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False,
    )
    # 'dividend' — дата закрытия реестра (отсечка); 'split' — дата дробления.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    # Последний день, когда покупка ещё даёт право на дивиденд (T+1: рабочий
    # день до реестра). Засечка ставится на следующий торговый день — там гэп.
    last_buy_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Дивиденд на акцию в валюте выплаты; у сплита — коэффициент «после ÷ до».
    value: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="moex")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
