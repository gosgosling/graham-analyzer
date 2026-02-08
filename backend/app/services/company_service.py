from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from app.models.company import Company
from app.schemas import CompanyCreate


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
    )
    db.add(db_company)
    db.commit()
    db.refresh(db_company)
    return db_company

def update_company(db: Session, isin: str, company_data: CompanyCreate) -> Optional[Company]:
    """
    Обновляет существующую компанию.
    
    Args:
        db: Сессия базы данных
        figi: FIGI компании для поиска
        company_data: Новые данные
        
    Returns:
        Обновленный объект Company или None, если не найдена
    """
    db_company = get_company_by_isin(db, isin)
    if not db_company:
        return None
    
    # Обновляем поля (type: ignore нужен из-за особенностей типизации SQLAlchemy дескрипторов)
    db_company.ticker = company_data.ticker  # type: ignore
    db_company.name = company_data.name  # type: ignore
    db_company.sector = company_data.sector  # type: ignore
    db_company.currency = company_data.currency  # type: ignore
    db_company.lot = company_data.lot  # type: ignore
    db_company.api_trade_available_flag = company_data.api_trade_available_flag  # type: ignore
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
    Это удобная функция для массовой синхронизации данных из API.
    
    Args:
        db: Сессия базы данных
        company_data: Данные компании
        
    Returns:
        Объект Company (созданный или обновленный)
    """

    existing_company = get_company_by_isin(db, company_data.isin)

    if existing_company:
        return update_company(db, company_data.isin, company_data)
    else:
        # Компании нет - создаем
        return create_company(db, company_data)