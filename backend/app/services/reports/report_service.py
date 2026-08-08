from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from datetime import date, datetime, timezone
from app.models.financial_report import FinancialReport
from app.models.company import Company
from app.schemas import FinancialReportCreate
from app.schemas.report import ReportFigures
from app.services.analysis import multiplier_service
from app.models.enums import company_type_to_report_type
from app.utils.date_parse import parse_date


# Поля показателей берём из самой схемы: список живёт в одном месте, и новое
# поле (например, кредитный портфель банка) начинает сохраняться без правки
# этого файла. Раньше здесь были два перечисления по сорок строк, и добавление
# поля молча терялось, если забыть одно из них.
_FIGURE_FIELDS: tuple[str, ...] = tuple(ReportFigures.model_fields)

# При обновлении эти поля не перезаписываются: verified_by_analyst обрабатывается
# отдельно ниже, остальные — технические метки AI-парсера.
_UPDATE_SKIP = frozenset({
    "auto_extracted",
    "verified_by_analyst",
    "extraction_model",
    "source_pdf_path",
})


def _figures_from(report_data) -> dict:
    """Значения показателей из схемы запроса — в аргументы модели."""
    return {name: getattr(report_data, name) for name in _FIGURE_FIELDS}


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
    # YYYY-MM-DD или DD.MM.YYYY (часто так возвращает LLM из аудиторского заключения)
    report_date_obj = parse_date(report_data.report_date)
    if report_date_obj is None:
        raise ValueError(f"Некорректная report_date: {report_data.report_date!r}")
    filing_date_obj = parse_date(report_data.filing_date) if report_data.filing_date else None

    # Автоматически определяем report_type из сектора компании
    company = db.query(Company).filter(Company.id == report_data.company_id).first()
    resolved_report_type = company_type_to_report_type(company.company_type if company else None)

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
        # Показатели отчёта — единым списком из схемы (см. _FIGURE_FIELDS)
        **_figures_from(report_data),
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
    
    report_date_obj = parse_date(report_data.report_date)
    if report_date_obj is None:
        raise ValueError(f"Некорректная report_date: {report_data.report_date!r}")
    filing_date_obj = parse_date(report_data.filing_date) if report_data.filing_date else None
    
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
    db_report.report_type = company_type_to_report_type(
        update_company.company_type if update_company else None
    )  # type: ignore
    # Даты
    db_report.report_date = report_date_obj  # type: ignore
    db_report.filing_date = filing_date_obj  # type: ignore
    # Показатели отчёта — единым списком из схемы. Технические метки AI
    # (auto_extracted, extraction_model, source_pdf_path) при ручной правке
    # не трогаем: их проставляет парсер.
    for _field in _FIGURE_FIELDS:
        if _field in _UPDATE_SKIP:
            continue
        setattr(db_report, _field, getattr(report_data, _field))

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
    Удаляет финансовый отчет и все связанные с ним report_based-мультипликаторы.

    На уровне схемы FK `multipliers.report_id` имеет ON DELETE SET NULL.
    Без дополнительной очистки это означало бы, что после удаления отчёта
    все его `report_based` мультипликаторы остаются в БД с `report_id=NULL`
    и превращаются в «сирот» — захламляют «Историю мультипликаторов» в UI.
    Поэтому удаляем их явно перед удалением самого отчёта.

    Записи `type='current'` НЕ удаляются — они относятся к сегодняшним
    котировкам и будут пересчитаны на следующем запросе актуальных
    мультипликаторов.

    Args:
        db: Сессия базы данных
        report_id: ID отчета для удаления

    Returns:
        True если удален успешно, False если не найден
    """
    db_report = get_report_by_id(db, report_id)
    if not db_report:
        return False

    # 1) Сначала чистим связанные мультипликаторы (type='report_based').
    multiplier_service.delete_multipliers_for_report(db, report_id=report_id)

    # 2) Удаляем сам отчёт.
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


def count_reports_by_company(db: Session) -> dict[int, int]:
    """
    Число финансовых отчётов по каждой компании (все отчёты).
    Компании без отчётов в результат не попадают — на фронте считают как 0.
    """
    from sqlalchemy import func as sa_func

    rows = (
        db.query(
            FinancialReport.company_id,
            sa_func.count(FinancialReport.id),
        )
        .group_by(FinancialReport.company_id)
        .all()
    )
    return {company_id: count for company_id, count in rows}
