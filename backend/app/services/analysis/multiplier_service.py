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
from app.models.enums import CompanyType
from app.services.analysis.fcf import compute_banking_flow, compute_core_fcf, compute_fcf
from app.services.analysis.sector_profiles import (
    profile_to_dict,
    resolve_profile,
)
from app.services.analysis.bank_metrics import (
    bank_metric_hint,
    compute_bank_metrics,
    evaluate_all,
)
from app.services.analysis.periods import is_full_year
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
# operating_expenses здесь ради Cost-to-Income: он должен считаться по той же
# паре периодов, что и выручка, иначе полугодовой отчёт делает банк вдвое
# эффективнее на бумаге. provisions и interest_expense — ради стоимости риска
# и фондирования: их тоже делят на баланс, и полугодие без пары исказило бы
# результат.
_LTM_BANK_ATTRS: Tuple[str, ...] = (
    "net_interest_income",
    "fee_commission_income",
    "operating_expenses",
    "provisions",
    "interest_expense",
)


_DIVIDEND_ATTRS = ("dividends_per_share", "special_dividends_per_share")


def _field_rub(report: FinancialReport, attr: str) -> Optional[float]:
    if attr in _DIVIDEND_ATTRS and not getattr(report, "dividends_paid", False):
        return None
    val = getattr(report, attr, None)
    if val is None:
        return None
    return _convert(val, report.currency, _to_float(report.exchange_rate))


def _flow_fields_rub(report: FinancialReport, is_bank: bool = False) -> Dict[str, Optional[float]]:
    """Потоковые поля одного отчёта за полный год — как есть, без агрегации.

    Банковские поля собираются всегда, а не только для report_type='bank':
    у гибрида финсегмент живёт внутри обычной отчётности, и его портфель с
    резервами тоже нужен в LTM. У промышленной компании эти поля пустые,
    поэтому лишними значениями это не оборачивается.
    """
    attrs = _LTM_FLOW_ATTRS + _LTM_BANK_ATTRS
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

    # Банковские потоки собираем для любой компании: у гибрида финсегмент
    # сидит внутри обычной отчётности, а у промышленной эти поля пустые.
    flow = _ltm_from_interim_formula(
        latest, prior_fy, prior_ytd, _LTM_FLOW_ATTRS + _LTM_BANK_ATTRS
    )
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
        "ltm_operating_expenses": flow.get("operating_expenses"),
        "ltm_provisions": flow.get("provisions"),
        "ltm_interest_expense": flow.get("interest_expense"),
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

def _previous_comparable_report(
    db: Session, report: FinancialReport
) -> Optional[FinancialReport]:
    """Предыдущий отчёт того же типа периода — для приростов баланса.

    Приросты (депозиты, кредиты) считаются только между сопоставимыми
    периодами: разница между полугодием и годом дала бы бессмыслицу.
    """
    return (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == report.company_id,
            FinancialReport.period_type == report.period_type,
            FinancialReport.report_date < report.report_date,
        )
        .order_by(FinancialReport.report_date.desc())
        .first()
    )


def _hybrid_banking_flow(
    db: Session,
    company: Company,
    balance_report: FinancialReport,
) -> Tuple[Optional[float], Optional[str]]:
    """Приток от роста клиентских остатков, млн ₽, и его основание.

    У компании со встроенным финбизнесом (Яндекс) и у биржи операционный поток включает
    прирост клиентских депозитов — чужие деньги, которые нельзя раздать
    акционерам. Считается до мультипликаторов: от этой величины зависит, по
    какому потоку строятся P/FCF, ND/FCF и FCF/NI. Для остальных типов
    компаний очистка не нужна — возвращаем None, и база остаётся прежней.
    """
    # Биржа — тот же случай, что гибрид: в операционный поток попадает движение
    # средств участников торгов и депонентов. Это чужие деньги, их нельзя
    # раздать акционерам и ими нельзя погасить долг.
    if getattr(company, "company_type", None) not in (
        CompanyType.HYBRID.value,
        CompanyType.EXCHANGE.value,
    ):
        return None, None

    previous = _previous_comparable_report(db, balance_report)
    banking_flow, basis = compute_banking_flow(balance_report, previous)
    if banking_flow is None:
        return None, None

    rate = _to_float(balance_report.exchange_rate)
    return _convert(banking_flow, balance_report.currency, rate), basis


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

    # Банковский поток считается ДО мультипликаторов: от него зависит, по
    # какому свободному потоку строить P/FCF, ND/FCF и FCF/NI у гибрида.
    banking_flow, banking_flow_basis = _hybrid_banking_flow(db, company, balance_report)

    # Кол-во акций для market cap — приоритет: в обращении → средневзв. → размещённые.
    mults = calculate_multipliers(
        report=balance_report,
        banking_flow=banking_flow,
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
        ltm_operating_expenses=_ltm_back_to_report_currency(
            ltm.get("ltm_operating_expenses"), balance_report
        ),
    )

    rate = _to_float(balance_report.exchange_rate)

    def crub(v):
        return _convert(v, balance_report.currency, rate)

    cap_basis = resolve_shares_cap_basis(balance_report, mults.get("shares_used"))

    return {
        **mults,
        "banking_flow": banking_flow,
        "banking_flow_basis": banking_flow_basis,
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


# Потоки, которые банковские показатели делят на баланс.
_BANK_METRIC_FLOWS = (
    ("net_income", "ltm_net_income"),
    ("net_interest_income", "ltm_net_interest_income"),
    ("provisions", "ltm_provisions"),
    ("interest_expense", "ltm_interest_expense"),
    ("revenue", "ltm_revenue"),
    ("fee_commission_income", "ltm_fee_commission_income"),
    ("operating_expenses", "ltm_operating_expenses"),
)


def compute_ltm_bank_metrics(db: Session, company_id: int) -> Optional[Dict]:
    """Показатели финансового бизнеса по скользящим двенадцати месяцам.

    Работает для двух типов компаний, и набор показателей у них разный:

    * **Кредитор** (`lender`) — весь набор: ROA, маржа, стоимость риска,
      фондирование, достаточность капитала. Отчётность банка целиком описывает
      финансовый бизнес, поэтому групповые показатели к нему и относятся.
    * **Гибрид** (`hybrid`) — только то, что относится к финсегменту:
      качество портфеля, стоимость риска, кредиты к депозитам, доли розницы.
      ROA, маржа и фондирование остаются пустыми намеренно: их знаменатели
      групповые, и «прибыль всего Яндекса ÷ активы всего Яндекса» ничего не
      говорит о его банке. Достаточность капитала гибрид не раскрывает вовсе —
      её показывает только сам банк в отчётности перед ЦБ.

    Отличие от `bank_metrics` в схеме отчёта — в числителе. Там показатели
    описывают один отчёт, и у полугодового приходится домножать поток на два,
    допуская, что второе полугодие будет как первое. Здесь берутся фактические
    двенадцать месяцев из формулы LTM, и допущения не нужно: ROA и стоимость
    риска считаются от того же периода, что P/E и ROE рядом в карточке.

    Знаменатели — балансовые, с самого свежего отчёта: портфель и депозиты
    берутся на отчётную дату, а не усредняются.

    Возвращает None, если у компании нет финансового бизнеса или отчётов нет.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    company_type = (getattr(company, "company_type", None) or "").strip().lower()
    is_exchange = company_type == CompanyType.EXCHANGE.value
    is_hybrid = company_type in (CompanyType.HYBRID.value, CompanyType.EXCHANGE.value)

    ltm = get_ltm_data(db, company_id)
    if ltm is None:
        return None

    balance_report: FinancialReport = ltm["balance_report"]
    is_lender = getattr(balance_report, "report_type", "general") == "bank"
    if not is_lender and not is_hybrid:
        return None

    flows = {
        attr: _ltm_back_to_report_currency(ltm.get(key), balance_report)
        for attr, key in _BANK_METRIC_FLOWS
    }

    metrics = compute_bank_metrics(
        balance_report,
        key_rate=_key_rate_for_year(db, balance_report.fiscal_year),
        ltm_flows=flows,
    )
    values = metrics.as_dict()

    if is_hybrid:
        # Групповые знаменатели к финсегменту не относятся — см. docstring.
        for name in _GROUP_LEVEL_METRICS:
            values[name] = None
    if is_exchange:
        # У биржи нет кредитного портфеля: показатели риска к ней неприменимы,
        # и пустые карточки читались бы как «данные не заполнены».
        for name in _CREDIT_METRICS:
            values[name] = None
    else:
        # Комиссии и клиентские остатки у банка описывают не то же самое:
        # у него доход от кредитования, а не от инфраструктуры.
        for name in _EXCHANGE_METRICS:
            values[name] = None

    statuses = evaluate_all(metrics)
    for name in values:
        if values.get(name) is None and name in statuses:
            statuses[name] = "n/a"
    hints = {
        name: hint
        for name in statuses
        if (hint := bank_metric_hint(name)) is not None
    }

    payload = {
        **values,
        "segment": "exchange" if is_exchange else "hybrid" if is_hybrid else "lender",
        "flow_basis": _flow_basis(metrics.flow_basis, ltm.get("source"), balance_report),
        "statuses": statuses,
        "hints": hints,
    }
    if is_hybrid:
        payload.update(_core_flow_summary(db, company, balance_report, ltm))
    return payload


# Показатели, знаменатель которых — весь баланс или весь отчёт о прибыли.
# Для банка это и есть финансовый бизнес, для гибрида — вся компания вместе с
# такси, доставкой и рекламой, поэтому финсегменту они не принадлежат.
# Показатели, которых у биржи нет: кредитного портфеля она не ведёт.
_CREDIT_METRICS = (
    "cost_of_risk",
    "npl_ratio",
    "npl_coverage",
    "npl_basis",
    "loans_to_deposits",
    "retail_loans_share",
    "retail_deposits_share",
    "gross_loans",
    "net_loans",
)

# Биржевые показатели: у банка и гибрида смысла не имеют.
_EXCHANGE_METRICS = ("fee_share", "opex_to_fees", "client_funds", "client_funds_to_equity")

_GROUP_LEVEL_METRICS = (
    "roa",
    "net_interest_margin",
    "cost_of_funding",
    "funding_spread",
    "capital_adequacy_ratio",
    "capital_adequacy_core",
    "capital_to_rwa",
    # Ключевая ставка — контекст для стоимости фондирования; без неё в шапке
    # это просто число, не относящееся к сегменту.
    "key_rate",
)


def _core_flow_summary(
    db: Session,
    company: Company,
    balance_report: FinancialReport,
    ltm: Dict,
) -> Dict[str, Optional[float]]:
    """Свободный поток ядра для панели финсегмента.

    Ровно те же три числа, что раньше жили в карточке мультипликаторов:
    поток по отчёту, приток от роста банковского баланса и разница между
    ними. Место у них здесь — рядом с портфелем и депозитами, из движения
    которых этот приток и складывается.
    """
    banking_flow, basis = _hybrid_banking_flow(db, company, balance_report)

    rate = _to_float(balance_report.exchange_rate)
    ocf = ltm.get("ltm_operating_cash_flow")
    capex = ltm.get("ltm_capex")
    lease = ltm.get("ltm_lease_principal")
    if ocf is None:
        ocf = _convert(balance_report.operating_cash_flow, balance_report.currency, rate)
    if capex is None:
        capex = _convert(balance_report.capex, balance_report.currency, rate)
    if lease is None:
        lease = _convert(balance_report.lease_principal, balance_report.currency, rate)

    reported_fcf = compute_fcf(ocf, capex, lease) if ocf is not None and capex is not None else None

    return {
        "reported_fcf": reported_fcf,
        "banking_flow": banking_flow,
        "banking_flow_basis": basis,
        "core_fcf": compute_core_fcf(reported_fcf, banking_flow),
    }


def _flow_basis(
    computed: Optional[str],
    ltm_source: Optional[str],
    balance_report: FinancialReport,
) -> Optional[str]:
    """Уточняет, чем на самом деле оказались потоки.

    `get_ltm_data` при нехватке прошлогоднего промежуточного отчёта отдаёт не
    скользящий год, а последний полный — те же двенадцать месяцев, но
    закончившиеся раньше отчётной даты. Числа настоящие, поэтому берём их (так
    же считаются P/E и ROE рядом), но называть это скользящим годом нельзя:
    прибыль за 2025 год, делённая на баланс середины 2026, занижает отдачу.
    """
    if computed != "ltm":
        return computed
    if is_full_year(balance_report):
        return "reported"
    if ltm_source == "annual":
        return "prior_full_year"
    return "ltm"


def _key_rate_for_year(db: Session, year: int) -> Optional[float]:
    """Средняя ключевая ставка ЦБ за год из справочника."""
    from app.models.key_rate import KeyRate

    row = db.query(KeyRate).filter(KeyRate.year == year).first()
    return float(row.avg_rate) if row else None


# ---------------------------------------------------------------------------
# Раскладка расчёта по колонкам Multiplier
# ---------------------------------------------------------------------------

# Метрики, которые ложатся в кэш под тем же именем, что и в расчёте.
_METRIC_FIELDS: Tuple[str, ...] = (
    "price_used",
    "shares_used",
    "market_cap",
    "pe_ratio",
    "pb_ratio",
    "pb_tangible",
    "goodwill",
    "goodwill_to_assets",
    "roe",
    "debt_to_equity",
    "current_ratio",
    "dividend_yield",
    "dividend_yield_regular",
    "cost_to_income",
    "ltm_fcf",
    "ltm_core_fcf",
    "ltm_operating_cash_flow",
    "ltm_capex",
    "price_to_fcf",
    "fcf_to_net_income",
    "net_debt",
    "net_debt_to_fcf",
)

# Поток для снимка «на сегодня» приходит из LTM-агрегации. В записи на дату
# отчёта те же колонки заполняются значениями самого отчёта (_report_flow_rub).
_LTM_FLOW_SNAPSHOT_FIELDS: Tuple[str, ...] = (
    "ltm_net_income",
    "ltm_revenue",
    "ltm_dividends_per_share",
    "ltm_special_dividends_per_share",
)

_BALANCE_FIELDS: Tuple[str, ...] = (
    "equity",
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
)


def _apply(row: Multiplier, values: Dict[str, Optional[float]]) -> None:
    """Проставляет колонки кэша по словарю.

    Раньше это были два списка присвоений по двадцать строк, скопированных
    друг у друга — и уже разошедшихся. Теперь список полей один, и добавление
    метрики Грэма правится в одном месте. Заодно уходит `# type: ignore` с
    каждой строки: у моделей SQLAlchemy аннотация `Mapped[Optional[float]]`
    не совпадает с типом присваиваемого значения, и pyright ругался на всё.
    """
    for field, value in values.items():
        setattr(row, field, value)


def _picked(mults: Dict, fields: Tuple[str, ...]) -> Dict[str, Optional[float]]:
    """Выбирает из расчёта только перечисленные поля."""
    return {field: mults.get(field) for field in fields}


def _balance_rub(report: FinancialReport) -> Dict[str, Optional[float]]:
    """Балансовые показатели отчёта, приведённые к рублям."""
    rate = _to_float(report.exchange_rate)
    return {
        field: _convert(getattr(report, field), report.currency, rate)
        for field in _BALANCE_FIELDS
    }


def _report_flow_rub(report: FinancialReport, mults: Dict) -> Dict[str, Optional[float]]:
    """Поток за период самого отчёта (в рублях) — для записи на дату отчёта.

    У годового отчёта LTM совпадает с самим годом, поэтому `ltm_*`-колонки
    заполняются значениями отчёта, а не агрегацией. Разовые дивиденды —
    исключение: их отделяет от регулярных сам расчёт.
    """
    rate = _to_float(report.exchange_rate)

    def crub(value):
        return _convert(value, report.currency, rate)

    ocf_rub = crub(report.operating_cash_flow)
    capex_rub = crub(report.capex)
    calculated_capex = mults.get("ltm_capex")

    return {
        "ltm_net_income": crub(report.net_income),
        "ltm_revenue": crub(report.revenue),
        "ltm_dividends_per_share": crub(report.dividends_per_share),
        "ltm_special_dividends_per_share": mults.get("ltm_special_dividends_per_share"),
        "ltm_operating_cash_flow": ocf_rub,
        "ltm_capex": calculated_capex if calculated_capex is not None else capex_rub,
        "ltm_fcf": compute_fcf(
            ocf_rub,
            capex_rub,
            crub(report.lease_principal),
            crub(report.lease_interest),
            crub(report.interest_paid),
            crub(report.debt_principal),
        ),
    }


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

    balance_report_id = mults.get("balance_report_id")
    _apply(existing, {"report_id": balance_report_id})
    _apply(existing, _picked(mults, _METRIC_FIELDS + _LTM_FLOW_SNAPSHOT_FIELDS))

    # Балансовые данные — из отчёта, на который опирается снимок (в рублях).
    if balance_report_id:
        report = db.query(FinancialReport).filter(FinancialReport.id == balance_report_id).first()
        if report:
            _apply(existing, _balance_rub(report))

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

    # Без цены год всё равно нужен в истории. До выхода на биржу цены не
    # существует, но выручка, прибыль, капитал и поток существуют — и именно
    # по ним видно, чем компания была до IPO. Подставлять вместо цены цену
    # размещения (так делают некоторые скринеры) нельзя: получится P/E, где
    # числитель из 2024 года, а знаменатель из 2021-го.
    #
    # Пропускаем только пустые черновики: если нет ни одной итоговой величины,
    # строка не несёт ничего, кроме года.
    has_content = any(
        getattr(report, field, None) is not None
        for field in ("revenue", "net_income", "equity", "total_assets")
    )
    if not has_content:
        # Мы не можем посчитать мультипликаторы — но «протухшие» записи
        # от предыдущих версий отчёта всё равно нужно вычистить.
        _delete_stale_report_based(db, report.id, keep_date=None)
        db.commit()
        return None

    # Поток ядра считается и для строк по годам, иначе колонка FCF в таблице
    # показывала бы сырой поток рядом с отношениями, посчитанными от ядра.
    # Приток берётся из ОДДС самого отчёта — за тот же период, что и поток.
    company = db.query(Company).filter(Company.id == report.company_id).first()
    banking_flow, _basis = (
        _hybrid_banking_flow(db, company, report) if company else (None, None)
    )

    mults = calculate_multipliers(report, banking_flow=banking_flow)

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

    _apply(existing, {"report_id": report.id})
    _apply(existing, _picked(mults, _METRIC_FIELDS))
    # Поток и баланс — из самого отчёта: для годового отчёта LTM = этот год.
    _apply(existing, _report_flow_rub(report, mults))
    _apply(existing, _balance_rub(report))

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
