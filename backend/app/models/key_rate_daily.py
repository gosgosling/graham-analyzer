"""Ключевая ставка ЦБ по дням — для оценки на каждую дату истории.

Годовой средней (`key_rates`) хватает, чтобы сравнить стоимость фондирования
банка с тем же годом. Для оценки на графике её мало: в 2015 году ставка шла
от 17% в январе до 11% в августе, и одна средняя 12,5% ставит весь год в
одинаковые условия, хотя инвестор в январе и в августе видел разные деньги.

Хранится каждый рабочий день, как его публикует ЦБ, а не только дни решений:
ряд проще сверять с источником, и строк немного — около двухсот пятидесяти в
год.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class KeyRateDaily(Base):
    __tablename__ = "key_rates_daily"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)  # % годовых
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="cbr")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
