from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from app.models.company import Company
from app.schemas import CompanyCreate


def detect_preferred_share(ticker: Optional[str]) -> bool:
    """Эвристика: MOEX-тикер привилегированных акций оканчивается на «P»
    (BANEP, TRNFP, SBERP, NKNCP …). Используется при создании компании
    через синхронизацию из T-Invest; ручной флажок имеет приоритет."""
    if not ticker:
        return False
    t = ticker.strip().upper()
    return len(t) >= 2 and t.endswith("P")


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
        else detect_preferred_share(company_data.ticker)
    )

    db_company = Company(
        figi=company_data.figi,
        ticker=company_data.ticker,
        name=company_data.name,
        isin=company_data.isin,
        sector=company_data.sector,
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
    db.commit()
    db.refresh(db_company)
    return db_company


def _instrument_can_be_preferred(company: Company) -> bool:
    """Тикер/название допускают режим «привилегированные акции»."""
    if detect_preferred_share(company.ticker):
        return True
    name = (company.name or "").lower()
    return "привилегирован" in name


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