"""
Сервис расчёта и кэширования мультипликаторов.

Логика LTM (Last Twelve Months):
- Показатели P&L (выручка, чистая прибыль, дивиденды):
    * Если есть 4 квартальных отчёта — суммируем их (TTM/LTM)
    * Если квартальных не хватает — используем последний годовой отчёт
- Балансовые данные (активы, капитал, обязательства):
    * Берём из самого свежего отчёта (квартального или годового)
"""
import logging
from datetime import date, datetime, timezone
from typing import Optional, List, Dict, Tuple

from sqlalchemy.orm import Session

from app.models.financial_report import FinancialReport
from app.models.multiplier import Multiplier
from app.models.company import Company
from app.models.enums import PeriodType
from app.services.analysis.calc_multipliers import calculate_multipliers
from app.utils.currency_converter import convert_to_rub

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LTM helpers
# ---------------------------------------------------------------------------

def _to_float(value) -> Optional[float]:
    return float(value) if value is not None else None


def _convert(value, currency: str, rate: Optional[float]) -> Optional[float]:
    return convert_to_rub(_to_float(value), currency, rate)


def get_ltm_data(db: Session, company_id: int) -> Optional[Dict]:
    """
    Вычисляет LTM финансовые данные для компании.

    Возвращает словарь:
        ltm_net_income       — чистая прибыль LTM (в валюте отчёта, конвертируется позже)
        ltm_revenue          — выручка LTM
        ltm_dividends_per_share — дивиденды на акцию LTM
        balance_report       — последний отчёт с балансовыми данными (объект FinancialReport)
        source               — "quarterly_4" | "annual" | None
    Все суммы в рублях (после конвертации).
    Если данных нет — возвращает None.
    """
    # Последние 4 квартальных отчёта (по дате, убывание)
    quarterly: List[FinancialReport] = (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == company_id,
            FinancialReport.period_type == PeriodType.QUARTERLY,
        )
        .order_by(FinancialReport.report_date.desc())
        .limit(4)
        .all()
    )

    # Последний годовой отчёт
    annual: Optional[FinancialReport] = (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == company_id,
            FinancialReport.period_type == PeriodType.ANNUAL,
        )
        .order_by(FinancialReport.report_date.desc())
        .first()
    )

    # Самый свежий отчёт для балансовых данных (любой тип)
    latest: Optional[FinancialReport] = (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .order_by(FinancialReport.report_date.desc())
        .first()
    )

    if latest is None:
        return None

    def sum_rub(reports: List[FinancialReport], attr: str) -> Optional[float]:
        """Суммирует поле по отчётам, конвертируя каждый в рубли."""
        total = 0.0
        has_any = False
        for r in reports:
            val = getattr(r, attr, None)
            if val is not None:
                rate = _to_float(r.exchange_rate)
                converted = _convert(val, r.currency, rate)
                if converted is not None:
                    total += converted
                    has_any = True
        return round(total, 2) if has_any else None

    # Используем 4 квартала, если доступны
    if len(quarterly) == 4:
        ltm_net_income = sum_rub(quarterly, "net_income")
        ltm_revenue = sum_rub(quarterly, "revenue")
        ltm_dividends = sum_rub(quarterly, "dividends_per_share")
        source = "quarterly_4"
    elif annual:
        rate = _to_float(annual.exchange_rate)
        ltm_net_income = _convert(annual.net_income, annual.currency, rate)
        ltm_revenue = _convert(annual.revenue, annual.currency, rate)
        ltm_dividends = _convert(annual.dividends_per_share, annual.currency, rate)
        source = "annual"
    else:
        # Только квартальный(е) без полного года — берём что есть
        reports_available = quarterly if quarterly else []
        ltm_net_income = sum_rub(reports_available, "net_income")
        ltm_revenue = sum_rub(reports_available, "revenue")
        ltm_dividends = sum_rub(reports_available, "dividends_per_share")
        source = f"quarterly_{len(reports_available)}"

    return {
        "ltm_net_income": ltm_net_income,
        "ltm_revenue": ltm_revenue,
        "ltm_dividends_per_share": ltm_dividends,
        "balance_report": latest,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Multiplier calculation & persistence
# ---------------------------------------------------------------------------

def calculate_current_multipliers(
    db: Session,
    company_id: int,
    price_override: Optional[float] = None,
) -> Optional[Dict]:
    """
    Рассчитывает актуальные мультипликаторы для компании.

    Args:
        db: Сессия БД
        company_id: ID компании
        price_override: Если передан — использует эту цену вместо company.current_price

    Returns:
        Словарь с мультипликаторами или None если данных недостаточно
    """
    company: Optional[Company] = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    ltm = get_ltm_data(db, company_id)
    if ltm is None:
        logger.warning("Нет отчётов для компании id=%d", company_id)
        return None

    balance_report: FinancialReport = ltm["balance_report"]

    # Определяем цену
    price = price_override
    if price is None:
        price = _to_float(company.current_price)
    if price is None:
        logger.warning("Нет текущей цены для компании id=%d (%s)", company_id, company.ticker)

    # Рассчитываем мультипликаторы
    # Поскольку LTM уже в рублях, передаём нулевой курс (не конвертировать повторно),
    # используя трюк: передаём значения через override-параметры.
    # Балансовые данные calc_multipliers конвертирует сам из balance_report.
    mults = calculate_multipliers(
        report=balance_report,
        override_price=price,
        ltm_net_income=_ltm_back_to_report_currency(
            ltm["ltm_net_income"], balance_report
        ),
        ltm_revenue=_ltm_back_to_report_currency(
            ltm["ltm_revenue"], balance_report
        ),
        ltm_dividends_per_share=_ltm_back_to_report_currency(
            ltm["ltm_dividends_per_share"], balance_report
        ),
    )

    return {
        **mults,
        "ltm_net_income": ltm["ltm_net_income"],
        "ltm_revenue": ltm["ltm_revenue"],
        "ltm_dividends_per_share": ltm["ltm_dividends_per_share"],
        "ltm_source": ltm["source"],
        "balance_report_id": balance_report.id,
        "balance_report_date": balance_report.report_date.isoformat(),
        "current_price": price,
        "company_id": company_id,
        "date": date.today().isoformat(),
    }


def _ltm_back_to_report_currency(
    rub_value: Optional[float],
    report: FinancialReport,
) -> Optional[float]:
    """
    LTM значения уже в рублях. Функция calc_multipliers будет повторно
    конвертировать через exchange_rate отчёта, поэтому нужно «откатить» обратно
    в валюту отчёта, чтобы итог снова вышел в рублях правильно.

    Если валюта отчёта RUB — просто возвращаем значение (конвертация = x1).
    Если USD с курсом — делим на курс.
    """
    if rub_value is None:
        return None
    if report.currency == "RUB" or not report.exchange_rate:
        return rub_value
    rate = float(report.exchange_rate)
    if rate == 0:
        return rub_value
    return round(rub_value / rate, 4)


# ---------------------------------------------------------------------------
# Cache (upsert) multiplier record
# ---------------------------------------------------------------------------

def save_current_multiplier(
    db: Session,
    company_id: int,
    mults: Dict,
) -> Multiplier:
    """
    Создаёт или обновляет запись актуальных мультипликаторов (type="current") на сегодня.
    """
    today = date.today()
    existing: Optional[Multiplier] = (
        db.query(Multiplier)
        .filter(
            Multiplier.company_id == company_id,
            Multiplier.date == today,
            Multiplier.type == "current",
        )
        .first()
    )

    if existing is None:
        existing = Multiplier(company_id=company_id, date=today, type="current")
        db.add(existing)

    existing.report_id = mults.get("balance_report_id")  # type: ignore
    existing.price_used = mults.get("price_used")  # type: ignore
    existing.shares_used = mults.get("shares_used")  # type: ignore
    existing.market_cap = mults.get("market_cap")  # type: ignore
    existing.ltm_net_income = mults.get("ltm_net_income")  # type: ignore
    existing.ltm_revenue = mults.get("ltm_revenue")  # type: ignore
    existing.ltm_dividends_per_share = mults.get("ltm_dividends_per_share")  # type: ignore
    existing.pe_ratio = mults.get("pe_ratio")  # type: ignore
    existing.pb_ratio = mults.get("pb_ratio")  # type: ignore
    existing.roe = mults.get("roe")  # type: ignore
    existing.debt_to_equity = mults.get("debt_to_equity")  # type: ignore
    existing.current_ratio = mults.get("current_ratio")  # type: ignore
    existing.dividend_yield = mults.get("dividend_yield")  # type: ignore

    # Балансовые данные из отчёта (в рублях)
    balance_report_id = mults.get("balance_report_id")
    if balance_report_id:
        report = db.query(FinancialReport).filter(FinancialReport.id == balance_report_id).first()
        if report:
            rate = _to_float(report.exchange_rate)

            def crub(v):
                return _convert(v, report.currency, rate)

            existing.equity = crub(report.equity)  # type: ignore
            existing.total_liabilities = crub(report.total_liabilities)  # type: ignore
            existing.current_assets = crub(report.current_assets)  # type: ignore
            existing.current_liabilities = crub(report.current_liabilities)  # type: ignore

    db.commit()
    db.refresh(existing)
    return existing


def save_report_based_multiplier(
    db: Session,
    report: FinancialReport,
) -> Optional[Multiplier]:
    """
    Вычисляет и сохраняет мультипликаторы на дату отчёта (type="report_based").
    Использует price_per_share из самого отчёта.
    Вызывается при создании/обновлении отчёта.
    """
    if report.price_per_share is None and report.shares_outstanding is None:
        return None

    mults = calculate_multipliers(report)

    existing: Optional[Multiplier] = (
        db.query(Multiplier)
        .filter(
            Multiplier.company_id == report.company_id,
            Multiplier.date == report.report_date,
            Multiplier.type == "report_based",
        )
        .first()
    )

    if existing is None:
        existing = Multiplier(
            company_id=report.company_id,
            date=report.report_date,
            type="report_based",
        )
        db.add(existing)

    existing.report_id = report.id  # type: ignore
    existing.price_used = mults.get("price_used")  # type: ignore
    existing.shares_used = mults.get("shares_used")  # type: ignore
    existing.market_cap = mults.get("market_cap")  # type: ignore
    existing.pe_ratio = mults.get("pe_ratio")  # type: ignore
    existing.pb_ratio = mults.get("pb_ratio")  # type: ignore
    existing.roe = mults.get("roe")  # type: ignore
    existing.debt_to_equity = mults.get("debt_to_equity")  # type: ignore
    existing.current_ratio = mults.get("current_ratio")  # type: ignore
    existing.dividend_yield = mults.get("dividend_yield")  # type: ignore

    rate = _to_float(report.exchange_rate)

    def crub(v):
        return _convert(v, report.currency, rate)

    existing.ltm_net_income = crub(report.net_income)  # type: ignore
    existing.ltm_revenue = crub(report.revenue)  # type: ignore
    existing.ltm_dividends_per_share = crub(report.dividends_per_share)  # type: ignore
    existing.equity = crub(report.equity)  # type: ignore
    existing.total_liabilities = crub(report.total_liabilities)  # type: ignore
    existing.current_assets = crub(report.current_assets)  # type: ignore
    existing.current_liabilities = crub(report.current_liabilities)  # type: ignore

    db.commit()
    db.refresh(existing)
    return existing


def get_multipliers_history(
    db: Session,
    company_id: int,
    mult_type: Optional[str] = None,
    limit: int = 365,
) -> List[Multiplier]:
    """
    Возвращает историю мультипликаторов компании (для построения графиков).

    Args:
        company_id: ID компании
        mult_type: Фильтр по типу ("report_based" | "current" | "daily")
        limit: Максимальное количество записей
    """
    q = db.query(Multiplier).filter(Multiplier.company_id == company_id)
    if mult_type:
        q = q.filter(Multiplier.type == mult_type)
    return q.order_by(Multiplier.date.desc()).limit(limit).all()


def get_latest_multiplier(
    db: Session,
    company_id: int,
    mult_type: str = "current",
) -> Optional[Multiplier]:
    """Возвращает последнюю запись мультипликаторов заданного типа."""
    return (
        db.query(Multiplier)
        .filter(Multiplier.company_id == company_id, Multiplier.type == mult_type)
        .order_by(Multiplier.date.desc())
        .first()
    )
