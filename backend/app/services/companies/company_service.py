from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import datetime, timezone
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.enums import CompanyType, company_type_to_report_type
from app.schemas import CompanyCreate
from app.services.analysis.sector_profiles import available_profiles
from app.services.companies.share_class import (
    detect_preferred_share,
    instrument_can_be_preferred,
)


def get_company_by_figi(db: Session, figi: str) -> Optional[Company]:
    """Поиск по FIGI — основной ключ при синхронизации с T-Invest (стабильнее ISIN)."""
    if not figi:
        return None
    return db.query(Company).filter(Company.figi == figi).first()


def get_company_by_isin(db: Session, isin: str) -> Optional[Company]:
    """
    Получает компанию по ISIN.
    
    Args:
        db: Сессия базы данных
        isin: ISIN компании
        
    Returns:
        Объект Company или None, если не найдена
    """
    return db.query(Company).filter(Company.isin == isin).first()

def get_company_by_id(db: Session, company_id: int) -> Optional[Company]:
    """
    Получает компанию по ID.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        
    Returns:
        Объект Company или None, если не найдена
    """
    return db.query(Company).filter(Company.id == company_id).first()


def get_company_by_ticker(db: Session, ticker: str) -> Optional[Company]:
    """Поиск компании по тикеру (без учёта регистра)."""
    if not ticker:
        return None
    t = ticker.strip().upper()
    return db.query(Company).filter(func.upper(Company.ticker) == t).first()

def create_company(db: Session, company_data: CompanyCreate) -> Company:
    """
    Создает новую компанию в БД.
    
    Args:
        db: Сессия базы данных
        company_data: Данные компании (Pydantic схема)
        
    Returns:
        Созданный объект Company
        
    Raises:
        IntegrityError: Если компания с таким FIGI уже существует
    """
    # Если флаг is_preferred_share явно не задан — пытаемся определить
    # по суффиксу тикера. Иначе используем переданное значение.
    is_pref = (
        company_data.is_preferred_share
        if company_data.is_preferred_share is not None
        else detect_preferred_share(company_data.ticker, company_data.name)
    )

    db_company = Company(
        figi=company_data.figi,
        ticker=company_data.ticker,
        name=company_data.name,
        isin=company_data.isin,
        sector=company_data.sector,
        sector_profile_key=company_data.sector_profile_key,
        currency=company_data.currency,
        lot=company_data.lot,
        api_trade_available_flag=company_data.api_trade_available_flag,
        brand_logo_url=company_data.brand_logo_url,
        brand_color=company_data.brand_color,
        is_preferred_share=is_pref,
    )
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company

def update_company(db: Session, isin: str, company_data: CompanyCreate) -> Optional[Company]:
    """
    Обновляет существующую компанию по ISIN (устаревший путь; предпочтительнее update_company_by_figi).
    """
    db_company = get_company_by_isin(db, isin)
    if not db_company:
        return None
    return _apply_company_update(db_company, company_data, db)


def update_company_by_figi(db: Session, figi: str, company_data: CompanyCreate) -> Optional[Company]:
    """Обновляет компанию по FIGI."""
    db_company = get_company_by_figi(db, figi)
    if not db_company:
        return None
    return _apply_company_update(db_company, company_data, db)


def _apply_company_update(db_company: Company, company_data: CompanyCreate, db: Session) -> Company:
    db_company.ticker = company_data.ticker  # type: ignore
    db_company.name = company_data.name  # type: ignore
    if company_data.isin:
        db_company.isin = company_data.isin  # type: ignore
    db_company.sector = company_data.sector  # type: ignore
    db_company.currency = company_data.currency  # type: ignore
    db_company.lot = company_data.lot  # type: ignore
    db_company.api_trade_available_flag = company_data.api_trade_available_flag  # type: ignore
    db_company.brand_logo_url = company_data.brand_logo_url  # type: ignore
    db_company.brand_color = company_data.brand_color  # type: ignore
    # is_preferred_share при апдейте из T-Invest НЕ перетираем — ручной
    # тумблер пользователя в карточке компании остаётся в приоритете.
    # Применяем только если значение явно передано (например, из PATCH).
    if company_data.is_preferred_share is not None:
        db_company.is_preferred_share = company_data.is_preferred_share  # type: ignore
    # Профиль порогов — тоже ручной выбор: синхронизация с T-Invest его не трогает.
    if company_data.sector_profile_key is not None:
        db_company.sector_profile_key = company_data.sector_profile_key  # type: ignore
    db.commit()
    db.refresh(db_company)
    return db_company


def _instrument_can_be_preferred(company: Company) -> bool:
    """Тикер/название допускают режим «привилегированные акции»."""
    return instrument_can_be_preferred(company.ticker, company.name)


def set_preferred_share_flag(
    db: Session, company_id: int, is_preferred: bool
) -> Optional[Company]:
    """Ручное переключение флажка «инструмент — привилегированные акции»
    из карточки компании. Возвращает обновлённый объект или None."""
    db_company = get_company_by_id(db, company_id)
    if not db_company:
        return None
    if is_preferred and not _instrument_can_be_preferred(db_company):
        # SIBN, GAZP и т.п. — только обыкновенный тикер, префов на MOEX нет.
        db_company.is_preferred_share = False  # type: ignore
    else:
        db_company.is_preferred_share = is_preferred  # type: ignore
    db.commit()
    db.refresh(db_company)
    return db_company


def set_sector_profile_key(
    db: Session, company_id: int, profile_key: Optional[str]
) -> Optional[Company]:
    """
    Закрепляет за компанией отраслевой профиль порогов.

    Пустое значение возвращает автоопределение по сектору. Неизвестный ключ
    отклоняется: молча свести пороги к грэмовским из-за опечатки — худший
    исход, чем явная ошибка.
    """
    db_company = get_company_by_id(db, company_id)
    if not db_company:
        return None
    cleaned = (profile_key or "").strip().lower()
    if cleaned and cleaned not in {p["key"] for p in available_profiles()}:
        raise ValueError(f"Неизвестный профиль: {profile_key}")
    db_company.sector_profile_key = cleaned or None  # type: ignore[assignment]
    db.commit()
    db.refresh(db_company)
    return db_company


def set_company_type(
    db: Session, company_id: int, company_type: str
) -> Optional[Company]:
    """Задаёт метод анализа компании.

    Тип определяет набор метрик и потому правится только вручную: сектор из
    T-Invest для этого непригоден — в `financial` лежат и Сбер, и АФК Система.
    При смене типа пересчитывается набор полей уже сохранённых отчётов, иначе
    у бывшего «банка» останутся банковские отчёты без банковского бизнеса.
    """
    db_company = get_company_by_id(db, company_id)
    if not db_company:
        return None

    cleaned = (company_type or "").strip().lower()
    allowed = {t.value for t in CompanyType}
    if cleaned not in allowed:
        raise ValueError(
            f"Неизвестный тип компании: {company_type!r}. Допустимо: {', '.join(sorted(allowed))}"
        )

    db_company.company_type = cleaned  # type: ignore[assignment]
    resolved = company_type_to_report_type(cleaned)
    db.query(FinancialReport).filter(FinancialReport.company_id == company_id).update(
        {FinancialReport.report_type: resolved}, synchronize_session=False
    )
    db.commit()
    db.refresh(db_company)
    return db_company


def set_business_description_manual(
    db: Session, company_id: int, description: Optional[str]
) -> Optional[Company]:
    """Ручное описание компании аналитиком (источник manual)."""
    db_company = get_company_by_id(db, company_id)
    if not db_company:
        return None
    cleaned = (description or "").strip()
    if cleaned:
        db_company.business_description = cleaned  # type: ignore[assignment]
        db_company.business_description_source = "manual"  # type: ignore[assignment]
    else:
        db_company.business_description = None  # type: ignore[assignment]
        db_company.business_description_source = None  # type: ignore[assignment]
    db_company.business_description_updated_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    db.commit()
    db.refresh(db_company)
    return db_company


def apply_business_description_from_llm(
    db: Session, company_id: int, description: str
) -> bool:
    """Обновить описание из LLM при парсинге отчёта.

    Не перезаписывает описание, если аналитик уже сохранил его вручную.
    """
    db_company = get_company_by_id(db, company_id)
    if not db_company:
        return False
    if db_company.business_description_source == "manual":
        return False
    cleaned = description.strip()
    if not cleaned:
        return False
    db_company.business_description = cleaned  # type: ignore[assignment]
    db_company.business_description_source = "llm"  # type: ignore[assignment]
    db_company.business_description_updated_at = datetime.now(timezone.utc)  # type: ignore[assignment]
    db.commit()
    return True


def get_all_companies(db: Session, skip: int = 0, limit: int = 200) -> List[Company]:
    """
    Получает все компании из БД.
    def get_all_companies(db: Session, skip: int = 0, limit: int = 100) -> List[Company]:
    return db.query(Company).offset(skip).limit(limit).all()
    """
    return db.query(Company).all()

def sync_company(db: Session, company_data: CompanyCreate) -> Company:
    """
    Синхронизирует компанию: создает, если не существует, или обновляет, если существует.
    Поиск существующей записи — по FIGI (уникален в T-Invest), затем fallback по ISIN.
    """
    existing = get_company_by_figi(db, company_data.figi)
    if existing:
        updated = update_company_by_figi(db, company_data.figi, company_data)
        if updated:
            return updated

    if company_data.isin:
        existing_isin = get_company_by_isin(db, company_data.isin)
        if existing_isin:
            return update_company(db, company_data.isin, company_data)

    return create_company(db, company_data)