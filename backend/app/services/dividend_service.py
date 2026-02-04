"""
Сервис для анализа непрерывности выплаты дивидендов по принципам Грэма.

Бенджамин Грэм считал важным критерием для инвестиций непрерывность выплаты дивидендов.
Он предпочитал компании, которые выплачивают дивиденды стабильно в течение многих лет.
"""

from sqlalchemy.orm import Session
from sqlalchemy import extract, func
from typing import List, Dict, Optional
from datetime import datetime, date
from app.models.financial_report import FinancialReport
from app.models.company import Company
from app.schemas import DividendContinuityResult


def calculate_dividend_continuity(
    db: Session, 
    company_id: int, 
    min_years: int = 20
) -> DividendContinuityResult:
    """
    Рассчитывает непрерывность выплаты дивидендов для компании.
    
    По принципам Грэма, компания должна выплачивать дивиденды непрерывно
    в течение минимум 20 лет чтобы считаться надежной инвестицией.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        min_years: Минимальное количество лет для считания непрерывными (по умолчанию 20)
        
    Returns:
        DividendContinuityResult с информацией о непрерывности выплат
    """
    # Получаем компанию
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise ValueError(f"Company with id {company_id} not found")
    
    # Получаем все отчеты компании, где выплачивались дивиденды
    reports_with_dividends = db.query(FinancialReport).filter(
        FinancialReport.company_id == company_id,
        FinancialReport.dividends_paid == True
    ).order_by(FinancialReport.report_date.asc()).all()
    
    if not reports_with_dividends:
        return DividendContinuityResult(
            company_id=company_id,
            dividend_start_year=company.dividend_start_year,
            years_of_continuous_payments=0,
            is_continuous=False,
            last_payment_year=None,
            gap_years=[],
            recommendation="Компания не выплачивает дивиденды или данные отсутствуют"
        )
    
    # Извлекаем годы из отчетов
    payment_years = sorted(set([report.report_date.year for report in reports_with_dividends]))
    
    if not payment_years:
        return DividendContinuityResult(
            company_id=company_id,
            dividend_start_year=company.dividend_start_year,
            years_of_continuous_payments=0,
            is_continuous=False,
            last_payment_year=None,
            gap_years=[],
            recommendation="Нет данных о выплате дивидендов"
        )
    
    # Определяем год начала выплат (из БД или из первого отчета)
    start_year = company.dividend_start_year or payment_years[0]
    last_year = payment_years[-1]
    current_year = datetime.now().year
    
    # Проверяем непрерывность: ищем пропуски в годах
    expected_years = set(range(start_year, last_year + 1))
    actual_years = set(payment_years)
    gap_years = sorted(list(expected_years - actual_years))
    
    # Количество лет непрерывных выплат (от начала до последнего года без пропусков)
    if gap_years:
        # Есть пропуски - считаем от последнего пропуска
        last_gap = gap_years[-1]
        years_of_continuous = current_year - last_gap - 1
    else:
        # Нет пропусков - считаем от начала
        years_of_continuous = current_year - start_year
    
    # Проверяем, выплачивались ли дивиденды в последнем году
    has_recent_payment = last_year >= current_year - 1
    
    # Определяем, является ли выплата непрерывной
    is_continuous = (
        len(gap_years) == 0 and  # Нет пропусков
        years_of_continuous >= min_years and  # Минимум 20 лет
        has_recent_payment  # Выплачивались в последние годы
    )
    
    # Формируем рекомендацию
    if is_continuous:
        recommendation = f"✅ Отличная непрерывность: {years_of_continuous} лет без перерывов"
    elif years_of_continuous >= min_years and len(gap_years) > 0:
        recommendation = f"⚠️ Хорошая история, но были пропуски в годах: {gap_years}"
    elif years_of_continuous < min_years:
        recommendation = f"❌ Недостаточная история выплат: {years_of_continuous} лет (требуется минимум {min_years})"
    else:
        recommendation = "❌ Нестабильная выплата дивидендов"
    
    return DividendContinuityResult(
        company_id=company_id,
        dividend_start_year=start_year,
        years_of_continuous_payments=years_of_continuous,
        is_continuous=is_continuous,
        last_payment_year=last_year,
        gap_years=gap_years,
        recommendation=recommendation
    )


def get_dividend_history(db: Session, company_id: int) -> List[Dict]:
    """
    Получает историю выплаты дивидендов компании.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        
    Returns:
        Список словарей с информацией о выплатах по годам
    """
    reports = db.query(FinancialReport).filter(
        FinancialReport.company_id == company_id,
        FinancialReport.dividends_paid == True
    ).order_by(FinancialReport.report_date.desc()).all()
    
    history = []
    for report in reports:
        history.append({
            "year": report.report_date.year,
            "date": report.report_date.isoformat(),
            "dividends_per_share": float(report.dividends_per_share) if report.dividends_per_share else None,
            "price_per_share": float(report.price_per_share) if report.price_per_share else None,
            "dividend_yield": (
                (float(report.dividends_per_share) / float(report.price_per_share) * 100)
                if report.dividends_per_share and report.price_per_share and report.price_per_share > 0
                else None
            )
        })
    
    return history


def update_dividend_start_year(db: Session, company_id: int) -> Optional[int]:
    """
    Автоматически обновляет год начала выплаты дивидендов на основе данных отчетов.
    
    Args:
        db: Сессия базы данных
        company_id: ID компании
        
    Returns:
        Год начала выплат или None
    """
    # Находим самый ранний отчет с дивидендами
    earliest_report = db.query(FinancialReport).filter(
        FinancialReport.company_id == company_id,
        FinancialReport.dividends_paid == True
    ).order_by(FinancialReport.report_date.asc()).first()
    
    if earliest_report:
        start_year = earliest_report.report_date.year
        # Обновляем компанию
        company = db.query(Company).filter(Company.id == company_id).first()
        if company:
            company.dividend_start_year = start_year
            db.commit()
        return start_year
    
    return None
