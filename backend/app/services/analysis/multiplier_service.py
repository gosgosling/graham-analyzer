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

from sqlalchemy.orm import Session, joinedload

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
        ltm_operating_cash_flow = sum_rub(quarterly, "operating_cash_flow")
        ltm_capex = sum_rub(quarterly, "capex")
        source = "quarterly_4"
    elif annual:
        rate = _to_float(annual.exchange_rate)
        ltm_net_income = _convert(annual.net_income, annual.currency, rate)
        ltm_revenue = _convert(annual.revenue, annual.currency, rate)
        ltm_dividends = _convert(annual.dividends_per_share, annual.currency, rate)
        ltm_operating_cash_flow = _convert(annual.operating_cash_flow, annual.currency, rate)
        ltm_capex = _convert(annual.capex, annual.currency, rate)
        source = "annual"
    else:
        # Только квартальный(е) без полного года — берём что есть
        reports_available = quarterly if quarterly else []
        ltm_net_income = sum_rub(reports_available, "net_income")
        ltm_revenue = sum_rub(reports_available, "revenue")
        ltm_dividends = sum_rub(reports_available, "dividends_per_share")
        ltm_operating_cash_flow = sum_rub(reports_available, "operating_cash_flow")
        ltm_capex = sum_rub(reports_available, "capex")
        source = f"quarterly_{len(reports_available)}"

    # Дополнительные банковские LTM-показатели (суммируем если report_type = "bank")
    is_bank = getattr(latest, "report_type", "general") == "bank"
    ltm_net_interest_income = None
    ltm_fee_commission_income = None
    if is_bank:
        reports_for_bank = quarterly if len(quarterly) == 4 else (
            [annual] if annual else (quarterly if quarterly else [])
        )
        ltm_net_interest_income = sum_rub(reports_for_bank, "net_interest_income")
        ltm_fee_commission_income = sum_rub(reports_for_bank, "fee_commission_income")

    return {
        "ltm_net_income": ltm_net_income,
        "ltm_revenue": ltm_revenue,
        "ltm_dividends_per_share": ltm_dividends,
        "ltm_operating_cash_flow": ltm_operating_cash_flow,
        "ltm_capex": ltm_capex,
        "ltm_net_interest_income": ltm_net_interest_income,
        "ltm_fee_commission_income": ltm_fee_commission_income,
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
        ltm_operating_cash_flow=_ltm_back_to_report_currency(
            ltm.get("ltm_operating_cash_flow"), balance_report
        ),
        ltm_capex=_ltm_back_to_report_currency(
            ltm.get("ltm_capex"), balance_report
        ),
    )

    return {
        **mults,
        "ltm_net_income": ltm["ltm_net_income"],
        "ltm_revenue": ltm["ltm_revenue"],
        "ltm_dividends_per_share": ltm["ltm_dividends_per_share"],
        "ltm_operating_cash_flow": ltm.get("ltm_operating_cash_flow"),
        "ltm_capex": ltm.get("ltm_capex"),
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
    existing.cost_to_income = mults.get("cost_to_income")  # type: ignore
    existing.ltm_fcf = mults.get("ltm_fcf")  # type: ignore
    existing.ltm_operating_cash_flow = mults.get("ltm_operating_cash_flow")  # type: ignore
    existing.price_to_fcf = mults.get("price_to_fcf")  # type: ignore
    existing.fcf_to_net_income = mults.get("fcf_to_net_income")  # type: ignore

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


def _delete_stale_report_based(
    db: Session,
    report_id: int,
    keep_date: Optional[date] = None,
    keep_id: Optional[int] = None,
) -> int:
    """
    Удаляет «протухшие» report_based-мультипликаторы, ссылающиеся на данный
    `report_id`, кроме тех, чья `date` совпадает с `keep_date` (или id совпадает
    с `keep_id`). Возвращает число удалённых строк.

    Применяется:
    * при UPDATE отчёта с изменением `report_date` — чтобы старая запись не
      висела с устаревшими shares/market_cap;
    * при DELETE отчёта — чтобы мультипликаторы не оставались «осиротевшими»
      с `report_id=NULL` (ON DELETE SET NULL без этой логики оставлял мусор).
    """
    q = db.query(Multiplier).filter(
        Multiplier.report_id == report_id,
        Multiplier.type == "report_based",
    )
    if keep_id is not None:
        q = q.filter(Multiplier.id != keep_id)
    if keep_date is not None:
        q = q.filter(Multiplier.date != keep_date)

    stale: List[Multiplier] = q.all()
    for row in stale:
        db.delete(row)
    if stale:
        logger.info(
            "Удалены %d устаревших report_based мультипликаторов для report_id=%d",
            len(stale),
            report_id,
        )
    return len(stale)


def delete_multipliers_for_report(db: Session, report_id: int) -> int:
    """
    Удаляет ВСЕ report_based мультипликаторы, привязанные к отчёту (любые даты).
    Вызывается перед удалением самого отчёта (`delete_report`), чтобы
    не оставлять «осиротевших» записей с `report_id=NULL`.

    `type='current'` записи не трогаем — они относятся к «сегодня» и
    после удаления отчёта будут пересчитаны на следующем запросе
    актуальных мультипликаторов (см. refresh endpoint).
    """
    rows = (
        db.query(Multiplier)
        .filter(
            Multiplier.report_id == report_id,
            Multiplier.type == "report_based",
        )
        .all()
    )
    for r in rows:
        db.delete(r)
    if rows:
        logger.info(
            "Удалены %d report_based мультипликаторов перед удалением отчёта id=%d",
            len(rows),
            report_id,
        )
    return len(rows)


def save_report_based_multiplier(
    db: Session,
    report: FinancialReport,
) -> Optional[Multiplier]:
    """
    Вычисляет и сохраняет мультипликаторы на дату отчёта (type="report_based").
    Использует price_per_share из самого отчёта.
    Вызывается при создании/обновлении отчёта.

    Ключ идемпотентности — `report_id` (один отчёт = одна report_based-запись).
    Раньше ключом была пара (company_id, date), но при UPDATE отчёта с
    изменением report_date это приводило к «сиротам»: старая запись оставалась
    привязанной к тому же report_id, но с устаревшей датой и устаревшими
    shares_used/market_cap. В «Истории мультипликаторов» появлялись дубли.
    Теперь мы чистим все прошлые report_based-записи этого report_id и
    пересоздаём/обновляем одну запись на актуальную report_date.
    """
    if report.price_per_share is None and report.shares_outstanding is None:
        # Мы не можем посчитать мультипликаторы — но «протухшие» записи
        # от предыдущих версий отчёта всё равно нужно вычистить.
        _delete_stale_report_based(db, report.id, keep_date=None)
        db.commit()
        return None

    mults = calculate_multipliers(report)

    # 1) Основная запись: ищем ранее созданную для ЭТОГО report_id.
    existing: Optional[Multiplier] = (
        db.query(Multiplier)
        .filter(
            Multiplier.report_id == report.id,
            Multiplier.type == "report_based",
        )
        .order_by(Multiplier.updated_at.desc().nullslast(), Multiplier.id.desc())
        .first()
    )

    if existing is None:
        # Fallback: вдруг существующая запись имеет report_id=NULL (осталась
        # после старого ON DELETE SET NULL) — найдём её по дате.
        existing = (
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
        # Нам нужен existing.id ниже (чтобы не удалить самих себя), поэтому
        # прогоняем flush — ID выдаётся сиквенсом и становится доступным.
        db.flush()
    else:
        # Сдвигаем дату на актуальную report_date (могла измениться при UPDATE).
        existing.date = report.report_date  # type: ignore
        # Гарантируем, что report_id проставлен (мог быть NULL после старой
        # логики ON DELETE SET NULL).
        existing.report_id = report.id  # type: ignore

    # 2) Чистим все прочие «протухшие» report_based для того же report_id —
    # это как раз источник дублей в UI (несколько записей на один отчёт).
    _delete_stale_report_based(
        db,
        report_id=report.id,
        keep_date=report.report_date,
        keep_id=existing.id,
    )

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
    existing.cost_to_income = mults.get("cost_to_income")  # type: ignore
    existing.ltm_fcf = mults.get("ltm_fcf")  # type: ignore
    existing.ltm_operating_cash_flow = mults.get("ltm_operating_cash_flow")  # type: ignore
    existing.price_to_fcf = mults.get("price_to_fcf")  # type: ignore
    existing.fcf_to_net_income = mults.get("fcf_to_net_income")  # type: ignore

    rate = _to_float(report.exchange_rate)

    def crub(v):
        return _convert(v, report.currency, rate)

    existing.ltm_net_income = crub(report.net_income)  # type: ignore
    existing.ltm_revenue = crub(report.revenue)  # type: ignore
    existing.ltm_dividends_per_share = crub(report.dividends_per_share)  # type: ignore
    existing.ltm_operating_cash_flow = crub(getattr(report, 'operating_cash_flow', None))  # type: ignore
    ocf_rub = crub(getattr(report, 'operating_cash_flow', None))
    cap_rub = crub(getattr(report, 'capex', None))
    existing.ltm_fcf = round(ocf_rub - cap_rub, 3) if (ocf_rub is not None and cap_rub is not None) else None  # type: ignore
    existing.price_to_fcf = mults.get("price_to_fcf")  # type: ignore
    existing.fcf_to_net_income = mults.get("fcf_to_net_income")  # type: ignore
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
    q = (
        db.query(Multiplier)
        .options(joinedload(Multiplier.report))
        .filter(Multiplier.company_id == company_id)
    )
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
