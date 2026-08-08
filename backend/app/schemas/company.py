"""Схемы компании: чтение, создание, обновление описания."""
from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel, field_serializer


class Company(BaseModel):
    """Схема для компании из Tinkoff Invest API"""
    id: Optional[int] = None  # ID из базы данных (может отсутствовать при создании)
    figi: str  # FIGI - уникальный идентификатор инструмента
    ticker: str  # Тикер
    name: str  # Название компании
    isin: str # ISIN для связи с MOEX
    sector: Optional[str] = None  # Сектор
    # Профиль порогов, закреплённый аналитиком (см. /companies/sector-profiles).
    # Пусто → определяется автоматически по сектору.
    sector_profile_key: Optional[str] = None
    company_type: str = "industrial"  # метод анализа: industrial|lender|insurance|holding|hybrid
    currency: str  # Валюта
    lot: int  # Размер лота
    api_trade_available_flag: bool = False  # Доступность для торговли через API
    brand_logo_url: Optional[str] = None  # URL логотипа (CDN Т-Банка)
    brand_color: Optional[str] = None  # Основной цвет бренда (#RRGGBB)
    # Тикер представляет привилегированные акции (см. модель Company)
    is_preferred_share: bool = False
    business_description: Optional[str] = None
    business_description_source: Optional[str] = None  # manual | llm
    business_description_updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True  # Для SQLAlchemy моделей

    @field_serializer('business_description_updated_at')
    def serialize_business_description_updated_at(
        self, v: Optional[Union[datetime, str]]
    ) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)


class CompanyDescriptionUpdate(BaseModel):
    """Тело PATCH /companies/{id}/description — ручное описание аналитиком."""
    business_description: Optional[str] = None


class CompanyCreate(BaseModel):
    figi: str
    ticker: str
    name: str
    isin: str
    sector: Optional[str] = None
    sector_profile_key: Optional[str] = None
    currency: str = "RUB"
    lot: int = 1
    api_trade_available_flag: bool = False
    dividend_start_year: Optional[int] = None  # Год начала выплаты дивидендов
    brand_logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    # Тикер представляет привилегированные акции. При синхронизации из
    # T-Invest автодетектится по суффиксу «P»; вручную правится через PATCH.
    is_preferred_share: Optional[bool] = None


# ---------------------------------------------------------------------------
# Company with current price
# ---------------------------------------------------------------------------

class CompanyWithPrice(BaseModel):
    """Расширенная схема компании с текущей ценой."""
    id: int
    figi: str
    ticker: str
    name: str
    isin: Optional[str] = None
    sector: Optional[str] = None
    currency: str
    lot: int
    current_price: Optional[float] = None
    price_updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
