"""
Сервис расчёта и кэширования мультипликаторов.

Логика LTM (Last Twelve Months) для потоковых показателей (P&L, Cash Flow):
    1. Последний отчёт — годовой → LTM = этот год (FY).
    2. Последний отчёт — промежуточный (полугодовой / квартальный, YTD):
       LTM = FY_{N-1} + YTD_N − YTD_{N-1}
       (напр. H1_2026 + FY2025 − H1_2025 → июль 2025 – июнь 2026;
       9М_2026 + FY2025 − 9М_2025 → октябрь 2025 – сентябрь 2026).
    3. Промежуточный отчёт за 4 квартала (YTD = весь год) — это и есть FY.
    4. Иначе — последний годовой отчёт целиком.
    5. Если ни того, ни другого нет — LTM не считается.

Промежуточные отчёты эмитенты публикуют нарастающим итогом (YTD): «6 месяцев»,
«9 месяцев». Складывать их между собой нельзя — 3М + 9М посчитает первый
квартал дважды, а четвёртый потеряет. Поэтому единственный способ получить
скользящий год из промежуточного отчёта — формула из пункта 2; когда данных
для неё не хватает, берётся годовой отчёт, а не суррогат из сумм.

Балансовые показатели (активы, капитал, долг, cash) — всегда из самого
свежего отчёта (latest), без LTM-агрегации.
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
from app.services.analysis.fcf import compute_fcf
from app.services.analysis.sector_profiles import (
    profile_to_dict,
    resolve_profile,
)
from app.services.analysis.share_counts import (
    compute_circulation_shares,
    resolve_shares_for_multipliers,
    resolve_shares_cap_basis,
)
from app.utils.currency_converter import convert_to_rub

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LTM helpers
# ---------------------------------------------------------------------------

def _to_float(value) -> Optional[float]:
    return float(value) if value is not None else None


def _convert(value, currency: str, rate: Optional[float]) -> Optional[float]:
    return convert_to_rub(_to_float(value), currency, rate)


_LTM_FLOW_ATTRS: Tuple[str, ...] = (
    "net_income",
    "revenue",
    "dividends_per_share",
    "special_dividends_per_share",
    "operating_cash_flow",
    "capex",
    "lease_principal",
    "lease_interest",
    "interest_paid",
    "debt_principal",
)
_LTM_BANK_ATTRS: Tuple[str, ...] = ("net_interest_income", "fee_commission_income")


_DIVIDEND_ATTRS = ("dividends_per_share", "special_dividends_per_share")


def _field_rub(report: FinancialReport, attr: str) -> Optional[float]:
    if attr in _DIVIDEND_ATTRS and not getattr(report, "dividends_paid", False):
        return None
    val = getattr(report, attr, None)
    if val is None:
        return None
    return _convert(val, report.currency, _to_float(report.exchange_rate))


def _flow_fields_rub(report: FinancialReport, is_bank: bool) -> Dict[str, Optional[float]]:
    """Потоковые поля одного отчёта за полный год — как есть, без агрегации."""
    attrs = _LTM_FLOW_ATTRS + (_LTM_BANK_ATTRS if is_bank else ())
    return {attr: _field_rub(report, attr) for attr in attrs}


def _covers_full_year(report: FinancialReport) -> bool:
    """YTD за четыре квартала — это уже год, отдельная агрегация не нужна."""
    return (
        report.period_type == PeriodType.QUARTERLY
        and report.fiscal_quarter == 4
    )


def _ltm_formula_field(
    current: FinancialReport,
    prior_fy: FinancialReport,
    prior_ytd: FinancialReport,
    attr: str,
) -> Optional[float]:
    cur = _field_rub(current, attr)
    fy = _field_rub(prior_fy, attr)
    ytd = _field_rub(prior_ytd, attr)
    if cur is None or fy is None or ytd is None:
        return None
    return round(cur + fy - ytd, 2)


def _ltm_from_interim_formula(
    current: FinancialReport,
    prior_fy: FinancialReport,
    prior_ytd: FinancialReport,
    attrs: Tuple[str, ...],
) -> Dict[str, Optional[float]]:
    return {
        attr: _ltm_formula_field(current, prior_fy, prior_ytd, attr)
        for attr in attrs
    }


def _find_matching_report(
    db: Session,
    company_id: int,
    *,
    period_type: PeriodType,
    fiscal_year: int,
    fiscal_quarter: Optional[int],
    anchor: FinancialReport,
) -> Optional[FinancialReport]:
    q = (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == company_id,
            FinancialReport.period_type == period_type,
            FinancialReport.fiscal_year == fiscal_year,
            FinancialReport.accounting_standard == anchor.accounting_standard,
            FinancialReport.consolidated == anchor.consolidated,
        )
    )
    if fiscal_quarter is None:
        q = q.filter(FinancialReport.fiscal_quarter.is_(None))
    else:
        q = q.filter(FinancialReport.fiscal_quarter == fiscal_quarter)
    return q.first()


def _interim_ltm_source_label(report: FinancialReport) -> str:
    if report.period_type == PeriodType.SEMI_ANNUAL:
        return "semi_annual_derived"
    if report.period_type == PeriodType.QUARTERLY and report.fiscal_quarter:
        return f"quarterly_{report.fiscal_quarter}_derived"
    return "interim_derived"


def _try_interim_ltm(
    db: Session,
    company_id: int,
    latest: FinancialReport,
) -> Optional[Tuple[Dict[str, Optional[float]], str]]:
    """LTM = prior FY + current YTD − prior-year same YTD (если все три отчёта есть)."""
    if latest.period_type == PeriodType.ANNUAL:
        return None

    prior_fy = _find_matching_report(
        db,
        company_id,
        period_type=PeriodType.ANNUAL,
        fiscal_year=latest.fiscal_year - 1,
        fiscal_quarter=None,
        anchor=latest,
    )
    prior_ytd = _find_matching_report(
        db,
        company_id,
        period_type=PeriodType(latest.period_type),
        fiscal_year=latest.fiscal_year - 1,
        fiscal_quarter=latest.fiscal_quarter,
        anchor=latest,
    )
    if prior_fy is None or prior_ytd is None:
        return None

    flow = _ltm_from_interim_formula(latest, prior_fy, prior_ytd, _LTM_FLOW_ATTRS)
    is_bank = getattr(latest, "report_type", "general") == "bank"
    if is_bank:
        bank = _ltm_from_interim_formula(latest, prior_fy, prior_ytd, _LTM_BANK_ATTRS)
        flow.update(bank)

    return flow, _interim_ltm_source_label(latest)


def _flow_to_ltm_payload(flow: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
    return {
        "ltm_net_income": flow.get("net_income"),
        "ltm_revenue": flow.get("revenue"),
        "ltm_dividends_per_share": flow.get("dividends_per_share"),
        "ltm_special_dividends_per_share": flow.get("special_dividends_per_share"),
        "ltm_operating_cash_flow": flow.get("operating_cash_flow"),
        "ltm_capex": flow.get("capex"),
        "ltm_lease_principal": flow.get("lease_principal"),
        "ltm_lease_interest": flow.get("lease_interest"),
        "ltm_interest_paid": flow.get("interest_paid"),
        "ltm_debt_principal": flow.get("debt_principal"),
        "ltm_net_interest_income": flow.get("net_interest_income"),
        "ltm_fee_commission_income": flow.get("fee_commission_income"),
    }


def get_ltm_data(db: Session, company_id: int) -> Optional[Dict]:
    """
    Вычисляет LTM финансовые данные для компании.

    Возвращает словарь:
        ltm_net_income       — чистая прибыль LTM (в валюте отчёта, конвертируется позже)
        ltm_revenue          — выручка LTM
        ltm_dividends_per_share — дивиденды на акцию LTM
        balance_report       — последний отчёт с балансовыми данными (объект FinancialReport)
        source               — "annual" | "semi_annual_derived" | "quarterly_3_derived" |
                               "ytd_full_year" | "insufficient"
    Все суммы в рублях (после конвертации).
    Если данных нет — возвращает None.

    ⚠️ Промежуточные отчёты должны содержать накопительные (YTD) значения
    за период с начала года — как в публикуемой отчётности эмитента.
    """
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

    is_bank = getattr(latest, "report_type", "general") == "bank"
    source: str
    flow: Dict[str, Optional[float]]

    if latest.period_type == PeriodType.ANNUAL:
        flow = _flow_fields_rub(latest, is_bank)
        source = "annual"
    else:
        interim = _try_interim_ltm(db, company_id, latest)
        if interim is not None:
            flow, source = interim
        elif _covers_full_year(latest):
            flow = _flow_fields_rub(latest, is_bank)
            source = "ytd_full_year"
        elif annual is not None:
            # Свежий YTD без прошлогодней пары в LTM не превращается: берём
            # последний полный год. Он устарел, но это честные 12 месяцев.
            flow = _flow_fields_rub(annual, is_bank)
            source = "annual"
        else:
            # Остались только промежуточные отчёты: 9 месяцев — это не год, а
            # сумма YTD-отчётов между собой считает одни кварталы дважды.
            # Лучше пустой мультипликатор, чем правдоподобно неверный.
            flow = {attr: None for attr in _LTM_FLOW_ATTRS + _LTM_BANK_ATTRS}
            source = "insufficient"
            logger.info(
                "LTM для company_id=%s не посчитан: есть только промежуточные "
                "отчёты (последний — %s %s), годового нет.",
                company_id,
                latest.period_type,
                latest.fiscal_year,
            )

    payload = _flow_to_ltm_payload(flow)
    return {
        **payload,
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

    # Кол-во акций для market cap — приоритет: в обращении → средневзв. → размещённые.
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
        ltm_special_dividends_per_share=_ltm_back_to_report_currency(
            ltm.get("ltm_special_dividends_per_share"), balance_report
        ),
        ltm_operating_cash_flow=_ltm_back_to_report_currency(
            ltm.get("ltm_operating_cash_flow"), balance_report
        ),
        ltm_capex=_ltm_back_to_report_currency(
            ltm.get("ltm_capex"), balance_report
        ),
        ltm_lease_principal=_ltm_back_to_report_currency(
            ltm.get("ltm_lease_principal"), balance_report
        ),
        ltm_lease_interest=_ltm_back_to_report_currency(
            ltm.get("ltm_lease_interest"), balance_report
        ),
        ltm_interest_paid=_ltm_back_to_report_currency(
            ltm.get("ltm_interest_paid"), balance_report
        ),
        ltm_debt_principal=_ltm_back_to_report_currency(
            ltm.get("ltm_debt_principal"), balance_report
        ),
    )

    rate = _to_float(balance_report.exchange_rate)

    def crub(v):
        return _convert(v, balance_report.currency, rate)

    cap_basis = resolve_shares_cap_basis(balance_report, mults.get("shares_used"))

    return {
        **mults,
        "ltm_net_income": ltm["ltm_net_income"],
        "ltm_revenue": ltm["ltm_revenue"],
        "ltm_dividends_per_share": ltm["ltm_dividends_per_share"],
        "ltm_special_dividends_per_share": ltm.get("ltm_special_dividends_per_share"),
        "ltm_operating_cash_flow": ltm.get("ltm_operating_cash_flow"),
        "ltm_capex": ltm.get("ltm_capex"),
        "ltm_source": ltm["source"],
        "balance_report_id": balance_report.id,
        "balance_report_date": balance_report.report_date.isoformat(),
        "current_price": price,
        "company_id": company_id,
        "date": date.today().isoformat(),
        "equity": crub(balance_report.equity),
        "total_assets": crub(balance_report.total_assets),
        "sector_profile": profile_to_dict(
            resolve_profile(
                company.sector,
                getattr(balance_report, "report_type", "general"),
                getattr(company, "sector_profile_key", None),
            )
        ),
        "shares_issued": balance_report.shares_issued,
        "shares_outstanding_circulation": compute_circulation_shares(
            balance_report.shares_outstanding,
            balance_report.shares_issued,
            balance_report.treasury_shares,
        ),
        "shares_cap_explanation": cap_basis["shares_cap_explanation"],
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
    existing.ltm_special_dividends_per_share = mults.get("ltm_special_dividends_per_share")  # type: ignore
    existing.pe_ratio = mults.get("pe_ratio")  # type: ignore
    existing.pb_ratio = mults.get("pb_ratio")  # type: ignore
    existing.roe = mults.get("roe")  # type: ignore
    existing.debt_to_equity = mults.get("debt_to_equity")  # type: ignore
    existing.current_ratio = mults.get("current_ratio")  # type: ignore
    existing.dividend_yield = mults.get("dividend_yield")  # type: ignore
    existing.dividend_yield_regular = mults.get("dividend_yield_regular")  # type: ignore
    existing.cost_to_income = mults.get("cost_to_income")  # type: ignore
    existing.ltm_fcf = mults.get("ltm_fcf")  # type: ignore
    existing.ltm_operating_cash_flow = mults.get("ltm_operating_cash_flow")  # type: ignore
    existing.ltm_capex = mults.get("ltm_capex")  # type: ignore
    existing.price_to_fcf = mults.get("price_to_fcf")  # type: ignore
    existing.fcf_to_net_income = mults.get("fcf_to_net_income")  # type: ignore
    existing.net_debt = mults.get("net_debt")  # type: ignore
    existing.net_debt_to_fcf = mults.get("net_debt_to_fcf")  # type: ignore

    # Балансовые данные из отчёта (в рублях)
    balance_report_id = mults.get("balance_report_id")
    if balance_report_id:
        report = db.query(FinancialReport).filter(FinancialReport.id == balance_report_id).first()
        if report:
            rate = _to_float(report.exchange_rate)

            def crub(v):
                return _convert(v, report.currency, rate)

            existing.equity = crub(report.equity)  # type: ignore
            existing.total_assets = crub(report.total_assets)  # type: ignore
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

    Промежуточные отчёты (полугодовые/квартальные) в историю не попадают —
    для них кэш report_based не создаётся (см. LTM в calculate_current_multipliers).
    """
    if report.period_type != PeriodType.ANNUAL:
        delete_multipliers_for_report(db, report.id)
        db.commit()
        return None

    if report.price_per_share is None and resolve_shares_for_multipliers(report) is None:
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
    existing.dividend_yield_regular = mults.get("dividend_yield_regular")  # type: ignore
    existing.cost_to_income = mults.get("cost_to_income")  # type: ignore
    existing.ltm_fcf = mults.get("ltm_fcf")  # type: ignore
    existing.ltm_operating_cash_flow = mults.get("ltm_operating_cash_flow")  # type: ignore
    existing.ltm_capex = mults.get("ltm_capex")  # type: ignore
    existing.price_to_fcf = mults.get("price_to_fcf")  # type: ignore
    existing.fcf_to_net_income = mults.get("fcf_to_net_income")  # type: ignore
    existing.net_debt = mults.get("net_debt")  # type: ignore
    existing.net_debt_to_fcf = mults.get("net_debt_to_fcf")  # type: ignore

    rate = _to_float(report.exchange_rate)

    def crub(v):
        return _convert(v, report.currency, rate)

    existing.ltm_net_income = crub(report.net_income)  # type: ignore
    existing.ltm_revenue = crub(report.revenue)  # type: ignore
    existing.ltm_dividends_per_share = crub(report.dividends_per_share)  # type: ignore
    existing.ltm_special_dividends_per_share = mults.get("ltm_special_dividends_per_share")  # type: ignore

    existing.ltm_operating_cash_flow = crub(getattr(report, 'operating_cash_flow', None))  # type: ignore
    existing.ltm_capex = mults.get("ltm_capex") if mults.get("ltm_capex") is not None else crub(getattr(report, 'capex', None))  # type: ignore
    ocf_rub = crub(getattr(report, 'operating_cash_flow', None))
    cap_rub = crub(getattr(report, 'capex', None))
    existing.ltm_fcf = compute_fcf(
        ocf_rub,
        cap_rub,
        crub(getattr(report, 'lease_principal', None)),
        crub(getattr(report, 'lease_interest', None)),
        crub(getattr(report, 'interest_paid', None)),
        crub(getattr(report, 'debt_principal', None)),
    )  # type: ignore
    existing.price_to_fcf = mults.get("price_to_fcf")  # type: ignore
    existing.fcf_to_net_income = mults.get("fcf_to_net_income")  # type: ignore
    existing.equity = crub(report.equity)  # type: ignore
    existing.total_assets = crub(report.total_assets)  # type: ignore
    existing.total_liabilities = crub(report.total_liabilities)  # type: ignore
    existing.current_assets = crub(report.current_assets)  # type: ignore
    existing.current_liabilities = crub(report.current_liabilities)  # type: ignore

    db.commit()
    db.refresh(existing)
    return existing


def backfill_report_based_multipliers(
    db: Session,
    company_id: int,
) -> dict[str, int]:
    """
    Пересчитывает report_based-мультипликаторы для **годовых** отчётов компании.
    Промежуточные отчёты пропускаются; их кэш report_based удаляется.

    Нужно после массового импорта или прямой SQL-вставки отчётов, когда
    create_report / update_report не вызывались и кэш истории пуст.
    """
    reports = (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .order_by(FinancialReport.report_date.asc())
        .all()
    )
    saved = 0
    skipped = 0
    for report in reports:
        if report.period_type != PeriodType.ANNUAL:
            delete_multipliers_for_report(db, report.id)
            skipped += 1
            continue
        result = save_report_based_multiplier(db, report)
        if result is not None:
            saved += 1
        else:
            skipped += 1
    db.commit()
    return {
        "total_reports": len(reports),
        "saved": saved,
        "skipped": skipped,
    }


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

    Для type=report_based в историю попадают только годовые отчёты —
    промежуточные (полугодовые/квартальные) используются лишь для расчёта
    актуального LTM, но не как отдельные строки таблицы.
    """
    q = (
        db.query(Multiplier)
        .options(joinedload(Multiplier.report))
        .filter(Multiplier.company_id == company_id)
    )
    if mult_type:
        q = q.filter(Multiplier.type == mult_type)
    if mult_type == "report_based":
        q = q.join(
            FinancialReport,
            Multiplier.report_id == FinancialReport.id,
        ).filter(FinancialReport.period_type == PeriodType.ANNUAL)
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
