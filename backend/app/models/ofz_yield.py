"""Доходность 10-летних ОФЗ по бескупонной кривой Мосбиржи — безрисковая ставка.

Формула оценки берёт K = безрисковая + премия, и безрисковая у Грэма —
доходность длинных государственных облигаций, а не ставка центробанка.
Пока их истории не было, на её месте стоял заменитель «ключевая + 1 пункт», и
он систематически врал: после шоков кривая переворачивается — ключевая выше
длинных ОФЗ, потому что рынок ждёт её снижения. В июне 2017 года заменитель
давал 11,0% при фактических 7,6%, в июне 2015-го — 13,6% при 10,6%.
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class OfzYield(Base):
    __tablename__ = "ofz_yields"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    # Бескупонная доходность на срок 10 лет, % годовых.
    y10: Mapped[float] = mapped_column(Numeric(7, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="moex_zcyc")
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
