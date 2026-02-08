from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import date, datetime
from app.models.financial_report import FinancialReport
from app.models.company import Company
from app.schemas import FinancialReportCreate


def create_report(db: Session, report_data: FinancialReportCreate) -> FinancialReport:
    """
    Создает новый финансовый отчет в БД.
    
    Args:
        db: Сессия базы данных
        report_data: Данные отчета (Pydantic схема)
        
    Returns:
        Созданный объект FinancialReport
        
    Raises:
        IntegrityError: Если отчет с такими параметрами уже существует
    """
    # Преобразуем строку даты в объект date
    report_date_obj = datetime.strptime(report_data.report_date, "%Y-%m-%d").date()
    
    db_report = FinancialReport(
        company_id=report_data.company_id,
        report_date=report_date_obj,
        price_per_share=report_data.price_per_share,
        shares_outstanding=report_data.shares_outstanding,
        revenue=report_data.revenue,
        net_income=report_data.net_income,
        total_assets=report_data.total_assets,
        current_assets=report_data.current_assets,
        total_liabilities=report_data.total_liabilities,
        current_liabilities=report_data.current_liabilities,
        equity=report_data.equity,
        dividends_per_share=report_data.dividends_per_share,
        dividends_paid=report_data.dividends_paid,
        currency=report_data.currency,
        exchange_rate=report_data.exchange_rate,
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    
    # Если отчет содержит дивиденды, обновляем год начала выплат
    if report_data.dividends_paid:
        _update_dividend_start_year_if_needed(db, report_data.company_id, report_date_obj.year)
    
    return db_report


def _update_dividend_start_year_if_needed(db: Session, company_id: int, report_year: int) -> None:
    """
    Внутренняя функция для обновления года начала выплаты дивидендов.
    Обновляет только если текущий год раньше сохраненного или если год не установлен.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        report_year: Год отчета с дивидендами
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company:
        if company.dividend_start_year is None or report_year < company.dividend_start_year:
            company.dividend_start_year = report_year  # type: ignore
            db.commit()


def get_report_by_id(db: Session, report_id: int) -> Optional[FinancialReport]:
    """
    Получает отчет по ID.
    
    Args:
        db: Сессия базы данных
        report_id: ID отчета
        
    Returns:
        Объект FinancialReport или None, если не найден
    """
    return db.query(FinancialReport).filter(FinancialReport.id == report_id).first()


def get_reports_by_company(
    db: Session, 
    company_id: int, 
    skip: int = 0, 
    limit: int = 100
) -> List[FinancialReport]:
    """
    Получает все отчеты для конкретной компании.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        skip: Количество пропущенных записей
        limit: Максимальное количество записей
        
    Returns:
        Список объектов FinancialReport
    """
    return (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .order_by(FinancialReport.report_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_all_reports(db: Session, skip: int = 0, limit: int = 200) -> List[FinancialReport]:
    """
    Получает все отчеты из БД.
    
    Args:
        db: Сессия базы данных
        skip: Количество пропущенных записей
        limit: Максимальное количество записей
        
    Returns:
        Список объектов FinancialReport
    """
    return (
        db.query(FinancialReport)
        .order_by(FinancialReport.report_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_report(
    db: Session, 
    report_id: int, 
    report_data: FinancialReportCreate
) -> Optional[FinancialReport]:
    """
    Обновляет существующий финансовый отчет.
    
    Args:
        db: Сессия базы данных
        report_id: ID отчета для обновления
        report_data: Новые данные отчета
        
    Returns:
        Обновленный объект FinancialReport или None, если не найден
    """
    db_report = get_report_by_id(db, report_id)
    if not db_report:
        return None
    
    # Преобразуем строку даты в объект date
    report_date_obj = datetime.strptime(report_data.report_date, "%Y-%m-%d").date()
    
    # Обновляем поля
    db_report.company_id = report_data.company_id  # type: ignore
    db_report.report_date = report_date_obj  # type: ignore
    db_report.price_per_share = report_data.price_per_share  # type: ignore
    db_report.shares_outstanding = report_data.shares_outstanding  # type: ignore
    db_report.revenue = report_data.revenue  # type: ignore
    db_report.net_income = report_data.net_income  # type: ignore
    db_report.total_assets = report_data.total_assets  # type: ignore
    db_report.current_assets = report_data.current_assets  # type: ignore
    db_report.total_liabilities = report_data.total_liabilities  # type: ignore
    db_report.current_liabilities = report_data.current_liabilities  # type: ignore
    db_report.equity = report_data.equity  # type: ignore
    db_report.dividends_per_share = report_data.dividends_per_share  # type: ignore
    db_report.dividends_paid = report_data.dividends_paid  # type: ignore
    db_report.currency = report_data.currency  # type: ignore
    db_report.exchange_rate = report_data.exchange_rate  # type: ignore
    
    db.commit()
    db.refresh(db_report)
    return db_report


def delete_report(db: Session, report_id: int) -> bool:
    """
    Удаляет финансовый отчет.
    
    Args:
        db: Сессия базы данных
        report_id: ID отчета для удаления
        
    Returns:
        True если удален успешно, False если не найден
    """
    db_report = get_report_by_id(db, report_id)
    if not db_report:
        return False
    
    db.delete(db_report)
    db.commit()
    return True


def get_latest_report(db: Session, company_id: int) -> Optional[FinancialReport]:
    """
    Получает последний (самый свежий) отчет для компании.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        
    Returns:
        Объект FinancialReport или None, если отчетов нет
    """
    return (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .order_by(FinancialReport.report_date.desc())
        .first()
    )
