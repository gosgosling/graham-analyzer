"""Средняя ключевая ставка ЦБ за год — база для оценки стоимости фондирования.

Стоимость фондирования банка (12% годовых) сама по себе не говорит ничего:
при ключевой ставке 4% это катастрофа, при 19% — отличный результат.
Смысл появляется только в сравнении со ставкой ТОГО ЖЕ периода, поэтому
хранится ряд по годам, а не текущее значение: отчёт 2022 года сравнивается
со средней за 2022-й, когда ставка ходила от 9,5% до 20%.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class KeyRate(Base):
    __tablename__ = "key_rates"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    avg_rate: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)  # % годовых
    # Откуда взята: 'cbr' — загружено скриптом с сайта ЦБ, 'manual' — вручную.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="cbr")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
