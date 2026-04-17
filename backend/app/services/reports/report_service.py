from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import date, datetime, timezone
from app.models.financial_report import FinancialReport
from app.models.company import Company
from app.schemas import FinancialReportCreate
from app.services.analysis import multiplier_service
from app.models.enums import sector_to_report_type


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
    # Преобразуем строки дат в объекты date
    report_date_obj = datetime.strptime(report_data.report_date, "%Y-%m-%d").date()
    filing_date_obj = None
    if report_data.filing_date:
        filing_date_obj = datetime.strptime(report_data.filing_date, "%Y-%m-%d").date()

    # Автоматически определяем report_type из сектора компании
    company = db.query(Company).filter(Company.id == report_data.company_id).first()
    resolved_report_type = sector_to_report_type(company.sector if company else None)

    db_report = FinancialReport(
        company_id=report_data.company_id,
        # Атрибуты отчёта
        period_type=report_data.period_type.value,
        fiscal_year=report_data.fiscal_year,
        fiscal_quarter=report_data.fiscal_quarter,
        accounting_standard=report_data.accounting_standard.value,
        consolidated=report_data.consolidated,
        source=report_data.source.value,
        report_type=resolved_report_type,
        # Даты
        report_date=report_date_obj,
        filing_date=filing_date_obj,
        # Рыночные данные
        price_per_share=report_data.price_per_share,
        price_at_filing=report_data.price_at_filing,
        shares_outstanding=report_data.shares_outstanding,
        # Финансовые данные
        revenue=report_data.revenue,
        net_income=report_data.net_income,
        net_income_reported=report_data.net_income_reported,
        total_assets=report_data.total_assets,
        current_assets=report_data.current_assets,
        total_liabilities=report_data.total_liabilities,
        current_liabilities=report_data.current_liabilities,
        equity=report_data.equity,
        dividends_per_share=report_data.dividends_per_share,
        dividends_paid=report_data.dividends_paid,
        currency=report_data.currency,
        exchange_rate=report_data.exchange_rate,
        # Банковские показатели
        net_interest_income=report_data.net_interest_income,
        fee_commission_income=report_data.fee_commission_income,
        operating_expenses=report_data.operating_expenses,
        provisions=report_data.provisions,
        # Верификация / источник AI
        auto_extracted=report_data.auto_extracted,
        verified_by_analyst=report_data.verified_by_analyst,
        extraction_notes=report_data.extraction_notes,
        extraction_model=report_data.extraction_model,
        source_pdf_path=report_data.source_pdf_path,
        verified_at=(
            datetime.now(timezone.utc) if report_data.verified_by_analyst else None
        ),
    )
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    
    # Если отчет содержит дивиденды, обновляем год начала выплат
    if report_data.dividends_paid:
        _update_dividend_start_year_if_needed(db, report_data.company_id, report_data.fiscal_year)

    # Автоматически кэшируем report_based мультипликаторы
    multiplier_service.save_report_based_multiplier(db=db, report=db_report)
    
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
    
    # Преобразуем строки дат в объекты date
    report_date_obj = datetime.strptime(report_data.report_date, "%Y-%m-%d").date()
    filing_date_obj = None
    if report_data.filing_date:
        filing_date_obj = datetime.strptime(report_data.filing_date, "%Y-%m-%d").date()
    
    # Обновляем поля
    db_report.company_id = report_data.company_id  # type: ignore
    # Атрибуты отчёта
    db_report.period_type = report_data.period_type.value  # type: ignore
    db_report.fiscal_year = report_data.fiscal_year  # type: ignore
    db_report.fiscal_quarter = report_data.fiscal_quarter  # type: ignore
    db_report.accounting_standard = report_data.accounting_standard.value  # type: ignore
    db_report.consolidated = report_data.consolidated  # type: ignore
    db_report.source = report_data.source.value  # type: ignore
    # report_type переопределяем из сектора компании (не из запроса)
    update_company = db.query(Company).filter(Company.id == report_data.company_id).first()
    db_report.report_type = sector_to_report_type(update_company.sector if update_company else None)  # type: ignore
    # Даты
    db_report.report_date = report_date_obj  # type: ignore
    db_report.filing_date = filing_date_obj  # type: ignore
    # Рыночные данные
    db_report.price_per_share = report_data.price_per_share  # type: ignore
    db_report.price_at_filing = report_data.price_at_filing  # type: ignore
    db_report.shares_outstanding = report_data.shares_outstanding  # type: ignore
    # Финансовые данные
    db_report.revenue = report_data.revenue  # type: ignore
    db_report.net_income = report_data.net_income  # type: ignore
    db_report.net_income_reported = report_data.net_income_reported  # type: ignore
    db_report.total_assets = report_data.total_assets  # type: ignore
    db_report.current_assets = report_data.current_assets  # type: ignore
    db_report.total_liabilities = report_data.total_liabilities  # type: ignore
    db_report.current_liabilities = report_data.current_liabilities  # type: ignore
    db_report.equity = report_data.equity  # type: ignore
    db_report.dividends_per_share = report_data.dividends_per_share  # type: ignore
    db_report.dividends_paid = report_data.dividends_paid  # type: ignore
    db_report.currency = report_data.currency  # type: ignore
    db_report.exchange_rate = report_data.exchange_rate  # type: ignore
    # Банковские показатели
    db_report.net_interest_income = report_data.net_interest_income  # type: ignore
    db_report.fee_commission_income = report_data.fee_commission_income  # type: ignore
    db_report.operating_expenses = report_data.operating_expenses  # type: ignore
    db_report.provisions = report_data.provisions  # type: ignore

    # Любая ручная правка через форму по умолчанию подтверждает корректность данных.
    # Схема FinancialReportCreate имеет verified_by_analyst=True по умолчанию, поэтому
    # старый фронт, не знающий о поле, автоматически получает verified=True.
    db_report.verified_by_analyst = report_data.verified_by_analyst  # type: ignore
    if report_data.verified_by_analyst and not db_report.verified_at:  # type: ignore
        db_report.verified_at = datetime.now(timezone.utc)  # type: ignore
    elif not report_data.verified_by_analyst:
        db_report.verified_at = None  # type: ignore
    # extraction_notes может править аналитик (например, добавить примечание). Остальные
    # extraction_* поля — технические и не меняются через обычный апдейт.
    db_report.extraction_notes = report_data.extraction_notes  # type: ignore

    db.commit()
    db.refresh(db_report)

    # Пересчитываем report_based мультипликаторы после обновления
    multiplier_service.save_report_based_multiplier(db=db, report=db_report)

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


# ─── Верификация отчётов аналитиком ──────────────────────────────────────────


def mark_report_verified(db: Session, report_id: int) -> Optional[FinancialReport]:
    """Помечает отчёт как проверенный финансовым аналитиком."""
    db_report = get_report_by_id(db, report_id)
    if not db_report:
        return None
    db_report.verified_by_analyst = True  # type: ignore
    db_report.verified_at = datetime.now(timezone.utc)  # type: ignore
    db.commit()
    db.refresh(db_report)
    return db_report


def mark_report_unverified(db: Session, report_id: int) -> Optional[FinancialReport]:
    """Снимает отметку проверки (возвращает отчёт в статус «требует проверки»)."""
    db_report = get_report_by_id(db, report_id)
    if not db_report:
        return None
    db_report.verified_by_analyst = False  # type: ignore
    db_report.verified_at = None  # type: ignore
    db.commit()
    db.refresh(db_report)
    return db_report


def get_unverified_reports(
    db: Session,
    company_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 200,
) -> List[FinancialReport]:
    """
    Возвращает список непроверенных отчётов (verified_by_analyst=False),
    опционально отфильтрованных по company_id.
    """
    query = db.query(FinancialReport).filter(
        FinancialReport.verified_by_analyst.is_(False)
    )
    if company_id is not None:
        query = query.filter(FinancialReport.company_id == company_id)
    return (
        query.order_by(FinancialReport.report_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def count_unverified_by_company(db: Session) -> dict[int, int]:
    """
    Возвращает словарь {company_id: число непроверенных отчётов}.
    Используется фронтом, чтобы подсветить компании с неподтверждёнными данными.
    """
    from sqlalchemy import func as sa_func

    rows = (
        db.query(
            FinancialReport.company_id,
            sa_func.count(FinancialReport.id),
        )
        .filter(FinancialReport.verified_by_analyst.is_(False))
        .group_by(FinancialReport.company_id)
        .all()
    )
    return {company_id: count for company_id, count in rows}
