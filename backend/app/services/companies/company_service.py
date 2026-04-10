from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from app.models.company import Company
from app.schemas import CompanyCreate


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