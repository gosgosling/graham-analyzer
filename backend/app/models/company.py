from sqlalchemy import Integer, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship 
from sqlalchemy.sql import func
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from app.database import Base
from app.models.enums import CompanyType

if TYPE_CHECKING:
    from app.models.financial_report import FinancialReport
    from app.models.stock_price import StockPrice
    from app.models.multiplier import Multiplier

class Company(Base):
    __tablename__ = "companies"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    figi: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    isin: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    sector: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Ручное закрепление отраслевого профиля порогов (ключ из sector_profiles).
    # T-Invest отдаёт сектор слишком крупными группами: весь потребительский
    # рынок приходит как "consumer", хотя пороги для продуктовой сети и для
    # магазина электроники разные. Пусто → профиль определяется по sector.
    sector_profile_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # Метод анализа компании — независимо от отрасли. Сектор `financial`
    # объединяет банки, страховщиков, биржи и холдинги, поэтому определять по
    # нему набор метрик нельзя: так АФК Система получала норматив Н1.
    company_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=CompanyType.INDUSTRIAL.value, index=True
    )
    currency: Mapped[str] = mapped_column(String, nullable=False, default="RUB")
    lot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    api_trade_available_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    # Бренд из T-Invest API (Shares.brand): логотип на CDN + фирменный цвет шапки
    brand_logo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    brand_color: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    
    # Год начала выплаты дивидендов (для анализа непрерывности по Грэму)
    dividend_start_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Тикер представляет привилегированные акции (TRNFP, BANEP, SBERP …).
    # Влияет на: интерпретацию dividends_per_share как доходности префов,
    # скрытие чекбокса «Есть привилегированные акции» в форме отчёта
    # и расчёт скорректированной прибыли/FCF.
    is_preferred_share: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Описание деятельности: ввод аналитиком или извлечение LLM из раздела
    # примечаний «1. Информация о компании» при парсинге отчёта.
    business_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_description_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    business_description_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Текущая цена акции (обновляется из T-Invest API раз в день)
    # Чистый долг корпоративного центра холдинга, млн ₽. В консолидированной
    # отчётности он не выделен (там долг всех дочек вместе), поэтому берётся
    # из презентаций эмитента и обновляется вручную — как и текущая цена.
    corporate_center_net_debt: Mapped[Optional[float]] = mapped_column(
        Numeric(15, 3), nullable=True
    )

    current_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    price_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Метаданные
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    stakes: Mapped[List["HoldingStake"]] = relationship(
        "HoldingStake",
        foreign_keys="HoldingStake.holding_company_id",
        back_populates="holding",
        cascade="all, delete-orphan",
    )

    reports: Mapped[List["FinancialReport"]] = relationship(
        "FinancialReport", 
        back_populates="company", 
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="FinancialReport.report_date.desc()"
    )

    stock_prices: Mapped[List["StockPrice"]] = relationship(
        "StockPrice",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="StockPrice.date.desc()",
    )

    multipliers: Mapped[List["Multiplier"]] = relationship(
        "Multiplier",
        back_populates="company",
        cascade="all, delete-orphan",
        lazy="dynamic",
        order_by="Multiplier.date.desc()",
    )