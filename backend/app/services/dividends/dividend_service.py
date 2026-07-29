"""
Сервис для анализа непрерывности выплаты дивидендов по принципам Грэма.

Бенджамин Грэм считал важным критерием для инвестиций непрерывность выплаты дивидендов.
Он предпочитал компании, которые выплачивают дивиденды стабильно в течение многих лет.
"""

from sqlalchemy.orm import Session
from typing import List, Dict, Optional, Sequence
from datetime import datetime
from app.models.financial_report import FinancialReport
from app.models.company import Company
from app.schemas import DividendContinuityResult


def _continuous_streak(payment_years: Sequence[int]) -> int:
    """Сколько лет подряд платили, считая назад от последней выплаты.

    Именно это имел в виду Грэм под непрерывностью: серия, которая длится до
    последней выплаты. Считать от текущего года нельзя — компания, платившая
    с 2010 по 2015 и с тех пор не платившая, получила бы «16 лет непрерывных
    выплат» в 2026 году.
    """
    if not payment_years:
        return 0
    streak = 1
    for i in range(len(payment_years) - 1, 0, -1):
        if payment_years[i - 1] != payment_years[i] - 1:
            break
        streak += 1
    return streak


def calculate_dividend_continuity(
    db: Session, 
    company_id: int, 
    min_years: int = 10
) -> DividendContinuityResult:
    """
    Рассчитывает непрерывность выплаты дивидендов для компании.

    У Грэма порог — 20 лет непрерывных выплат. Для российского рынка он
    недостижим (сама биржа моложе), поэтому по умолчанию берётся 10 лет:
    это адаптация, а не оригинальный критерий.

    Args:
        db: Сессия базы данных
        company_id: ID компании
        min_years: Минимальная длина серии выплат (по умолчанию 10)

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
    
    # Длина серии, заканчивающейся последней выплатой.
    years_of_continuous = _continuous_streak(payment_years)

    # Дивиденд за прошлый год объявляют уже в этом — отставание на год нормально.
    has_recent_payment = last_year >= current_year - 1

    is_continuous = years_of_continuous >= min_years and has_recent_payment

    if is_continuous:
        recommendation = f"✅ Отличная непрерывность: {years_of_continuous} лет без перерывов"
    elif years_of_continuous >= min_years and not has_recent_payment:
        recommendation = (
            f"⚠️ Серия из {years_of_continuous} лет прервана: "
            f"последняя выплата за {last_year} год"
        )
    elif gap_years:
        recommendation = (
            f"⚠️ Серия выплат — {years_of_continuous} лет "
            f"(требуется минимум {min_years}); были пропуски: {gap_years}"
        )
    else:
        recommendation = (
            f"❌ Недостаточная история выплат: {years_of_continuous} лет "
            f"(требуется минимум {min_years})"
        )
    
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
