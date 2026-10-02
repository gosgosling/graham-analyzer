"""Значения биржевых индексов по дням: рынок акций и рынок госдолга.

Для раздела «Рынок»: индекс Мосбиржи как торговался (IMOEX), он же с
реинвестированными дивидендами (MCFTR) и индекс гособлигаций RGBI. У RGBI
Мосбиржа вместе с ценой отдаёт доходность и дюрацию — по доходности видно,
сколько платит госдолг, по цене — что с ним происходило.

Там же лежат ряды для графика нефтяных компаний: BRENT ($/барр., FRED) и
USDRUB (курс ЦБ) — см. services/market/oil_service.py.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class MarketIndexValue(Base):
    __tablename__ = "market_index_values"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    close: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    # Только у облигационных индексов: эффективная доходность, % годовых,
    # и дюрация, дни.
    yield_pct: Mapped[Optional[float]] = mapped_column(Numeric(7, 3), nullable=True)
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
