"""Доли холдинга в дочерних компаниях — основа оценки по NAV.

У холдинга нет собственных операций: его стоимость складывается из долей и
уменьшается на долг корпоративного центра. Консолидированная отчётность для
этого не годится — она показывает выручку и активы дочек целиком, хотя
акционеру принадлежит только доля.

Публичная дочка ссылается на карточку компании: цена и количество акций уже
есть в базе, и капитализация пересчитывается сама. Непубличная (Медси, Степь,
Биннофарм) оценивается вручную — иначе её пришлось бы просто игнорировать.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.company import Company


class HoldingStake(Base):
    __tablename__ = "holding_stakes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    holding_company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    holding: Mapped["Company"] = relationship(
        "Company", foreign_keys=[holding_company_id], back_populates="stakes"
    )

    # Публичная дочка — ссылка на её карточку: капитализация считается из
    # текущей цены и количества акций, отдельного ввода не требует.
    subsidiary_company_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subsidiary: Mapped[Optional["Company"]] = relationship(
        "Company", foreign_keys=[subsidiary_company_id]
    )

    # Название нужно и непубличным активам, и как подпись, если карточку
    # дочки потом удалят: доля не должна превращаться в безымянную строку.
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    share_pct: Mapped[float] = mapped_column(Numeric(6, 3), nullable=False)  # доля владения, %

    # Оценка стоимости ВСЕЙ дочки для непубличных активов, млн ₽.
    # Для публичных остаётся пустой: там считает рынок.
    manual_valuation: Mapped[Optional[float]] = mapped_column(
        Numeric(15, 3), nullable=True
    )
    valuation_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
