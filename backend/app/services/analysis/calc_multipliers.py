from app.models.financial_report import FinancialReport
from app.services.analysis.share_counts import resolve_shares_for_multipliers
from app.services.analysis.fcf import compute_core_fcf, compute_fcf
from app.services.analysis.net_debt import compute_net_debt
from app.utils.currency_converter import convert_to_rub
from typing import Dict, Optional

# ⚠️ Финансовые показатели (P&L, баланс, ОДДС) хранятся в МИЛЛИОНАХ валюты.
# Цена акции и дивиденды на акцию — в полных единицах (₽ или $ за акцию).
# Количество акций — в штуках.
#
# Для расчёта P/E и P/B необходимо привести показатели к одним единицам:
#   market_cap = price_per_share × shares_outstanding  → полные рубли
#   net_income, equity и т.д. → млн ₽ × MILLION = полные рубли
#
# ROE, D/E, Current Ratio, FCF/NI — безразмерные отношения, миллионы сокращаются.
# Dividend Yield — оба значения в полных рублях на акцию.
# P/FCF = market_cap_full / (fcf_mln × MILLION) — аналогично P/E.

MILLION = 1_000_000


def calculate_multipliers(
    report: FinancialReport,
    override_price: Optional[float] = None,
    override_shares: Optional[int] = None,
    ltm_net_income: Optional[float] = None,
    ltm_revenue: Optional[float] = None,
    ltm_dividends_per_share: Optional[float] = None,
    ltm_special_dividends_per_share: Optional[float] = None,
    ltm_operating_cash_flow: Optional[float] = None,
    ltm_capex: Optional[float] = None,
    ltm_lease_principal: Optional[float] = None,
    ltm_lease_interest: Optional[float] = None,
    ltm_interest_paid: Optional[float] = None,
    ltm_debt_principal: Optional[float] = None,
    ltm_operating_expenses: Optional[float] = None,
    banking_flow: Optional[float] = None,
) -> Dict[str, Optional[float]]:
    """
    Рассчитывает финансовые мультипликаторы.

    Поведение зависит от report.report_type:
    - "general": стандартный набор (P/E, P/B, ROE, D/E, Current Ratio, Dividend Yield,
                                    P/FCF, FCF/Net Income)
    - "bank": банковский набор (P/E, P/B, ROE, Dividend Yield, Cost-to-Income)
              D/E, Current Ratio и FCF-показатели не рассчитываются — для банков не применимы.

    Args:
        report: Финансовый отчёт (источник балансовых данных и валюты)
        override_price: Переопределить цену акции (в полных ₽/$ за акцию)
        override_shares: Переопределить количество акций
        ltm_net_income: LTM чистая прибыль в млн валюты отчёта (None → из отчёта)
        ltm_revenue: LTM выручка / Total Operating Income в млн (None → из отчёта)
        ltm_dividends_per_share: LTM дивиденды на акцию в ₽/$ (None → из отчёта)
        ltm_special_dividends_per_share: разовая часть LTM-дивидендов в ₽/$ (None → из отчёта)
        ltm_operating_cash_flow: LTM операционный поток в млн валюты отчёта (None → из отчёта)
        ltm_capex: LTM CAPEX (положит. число) в млн валюты отчёта (None → из отчёта)
        ltm_operating_expenses: LTM операционные расходы банка в млн (пара к ltm_revenue
            для Cost-to-Income; без неё CIR считается по одному отчёту)
        banking_flow: приток от роста банковского баланса гибрида, млн РУБЛЕЙ
            (уже сконвертирован). Если передан — P/FCF, ND/FCF и FCF/NI
            считаются от потока ядра: приток клиентских денег акционеру не
            принадлежит и долг им не погасить. None — у компании нет
            финсегмента либо строки ОДДС не заполнены.

    Returns:
        Словарь с мультипликаторами. market_cap — в МИЛЛИОНАХ рублей.
    """
    report_type = getattr(report, 'report_type', 'general')
    is_bank = report_type == 'bank'
    # Биржа: плечо и ликвидность неприменимы по той же причине, что у банка —
    # обязательства это чужие деньги и зеркальные позиции клиринга. Но
    # кредитного портфеля у неё нет, а свободный поток есть и осмыслен,
    # поэтому FCF считается, в отличие от банка.
    is_exchange = report_type == 'exchange'
    no_leverage = is_bank or is_exchange

    rate = float(report.exchange_rate) if report.exchange_rate else None
    currency = report.currency

    def to_rub_full(value) -> Optional[float]:
        """Конвертировать полное значение (цена на акцию) в рубли."""
        return convert_to_rub(float(value) if value is not None else None, currency, rate)

    def to_rub_mln(value) -> Optional[float]:
        """Конвертировать значение в млн валюты → млн рублей."""
        return convert_to_rub(float(value) if value is not None else None, currency, rate)

    # Цена и количество акций (полные единицы)
    price_raw = override_price if override_price is not None else report.price_per_share
    price_rub = to_rub_full(price_raw)
    shares = override_shares if override_shares is not None else resolve_shares_for_multipliers(report)

    # P&L (в млн валюты → млн рублей)
    net_income_mln = (
        to_rub_mln(ltm_net_income) if ltm_net_income is not None
        else to_rub_mln(report.net_income)
    )
    # Дивиденды на акцию (только обыкновенные; поле dividends_per_share).
    # Если ltm_dividends_per_share передан явно — используем его.
    # При прямом чтении из отчёта — учитываем флаг dividends_paid:
    # если выплат не было (dividends_paid=False), dividend_yield должен быть None.
    _report_dps = report.dividends_per_share if getattr(report, "dividends_paid", False) else None
    dividends_per_share_rub = (
        to_rub_full(ltm_dividends_per_share) if ltm_dividends_per_share is not None
        else to_rub_full(_report_dps)
    )
    # Разовая часть выплаты (спецдивиденд, компенсация пропущенных лет).
    # Хранится как доля от общей DPS, поэтому регулярная = общая − разовая.
    _report_special = (
        getattr(report, "special_dividends_per_share", None)
        if getattr(report, "dividends_paid", False) else None
    )
    special_dividends_rub = (
        to_rub_full(ltm_special_dividends_per_share)
        if ltm_special_dividends_per_share is not None
        else to_rub_full(_report_special)
    )

    # Балансовые (в млн валюты → млн рублей)
    equity_mln = to_rub_mln(report.equity)
    total_liabilities_mln = to_rub_mln(report.total_liabilities)
    current_assets_mln = to_rub_mln(report.current_assets)
    current_liabilities_mln = to_rub_mln(report.current_liabilities)

    # Рыночная капитализация в полных рублях, затем переводим в млн для хранения
    market_cap_full: Optional[float] = None
    market_cap_mln: Optional[float] = None
    if price_rub and shares:
        market_cap_full = price_rub * shares
        market_cap_mln = round(market_cap_full / MILLION, 3)

    # P/E = Market Cap (полн. руб.) / Net Income (полн. руб.)
    pe_ratio: Optional[float] = None
    if market_cap_full and net_income_mln and net_income_mln > 0:
        pe_ratio = round(market_cap_full / (net_income_mln * MILLION), 2)

    # P/B = Market Cap (полн.) / Equity (полн.)
    pb_ratio: Optional[float] = None
    if market_cap_full and equity_mln and equity_mln > 0:
        pb_ratio = round(market_cap_full / (equity_mln * MILLION), 2)

    # ROE = Net Income / Equity × 100%  (миллионы сокращаются)
    roe: Optional[float] = None
    if net_income_mln is not None and equity_mln and equity_mln != 0:
        roe = round(net_income_mln / equity_mln * 100, 2)

    # Dividend Yield = Dividends per Share / Price × 100%  (оба в полных рублях)
    dividend_yield: Optional[float] = None
    if dividends_per_share_rub and price_rub and price_rub > 0:
        dividend_yield = round(dividends_per_share_rub / price_rub * 100, 2)

    # Регулярная доходность — без разовых выплат. Если разовая часть не
    # размечена, регулярная совпадает с общей.
    dividend_yield_regular: Optional[float] = None
    if dividends_per_share_rub and price_rub and price_rub > 0:
        regular_dps = dividends_per_share_rub - (special_dividends_rub or 0.0)
        dividend_yield_regular = round(max(regular_dps, 0.0) / price_rub * 100, 2)

    # ─── Показатели, зависящие от типа отрасли ───────────────────────────────
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    cost_to_income: Optional[float] = None
    ltm_fcf_mln: Optional[float] = None
    ltm_core_fcf_mln: Optional[float] = None
    fcf_basis: str = "reported"
    ltm_ocf_mln: Optional[float] = None
    ltm_capex_mln: Optional[float] = None
    price_to_fcf: Optional[float] = None
    fcf_to_net_income: Optional[float] = None
    net_debt_mln: Optional[float] = None
    net_debt_to_fcf: Optional[float] = None

    debt_mln = to_rub_mln(report.debt)
    cash_mln = to_rub_mln(report.cash_and_equivalents)
    # У биржи чистый долг считать нельзя: в «денежных средствах» лежат деньги
    # участников торгов и депонентов. У МОЕХ это дало бы −692 млрд, то есть
    # «свободная денежная позиция размером в три капитализации», хотя вернуть
    # эти деньги придётся по первому требованию.
    net_debt_mln = None if is_exchange else compute_net_debt(debt_mln, cash_mln)

    if no_leverage:
        # Для банков и бирж D/E и Current Ratio не применяются:
        # депозиты — обязательства по природе, D/E 8-10x — норма.
        # Вместо них рассчитываем Cost-to-Income (CIR).
        #
        # CIR = Operating Expenses / Total Operating Income × 100%
        # revenue хранит Total Operating Income для банков
        #
        # Числитель и знаменатель обязаны покрывать один период. Раньше здесь
        # бралась LTM-выручка за двенадцать месяцев и расходы прямо из отчёта:
        # для полугодового отчёта это давало CIR вдвое ниже настоящего — банк
        # выглядел бы вдвое эффективнее ровно в момент выхода промежуточной
        # отчётности. Поэтому пара берётся целиком либо LTM, либо из отчёта.
        if ltm_revenue is not None and ltm_operating_expenses is not None:
            revenue_for_cir = to_rub_mln(ltm_revenue)
            opex_mln = to_rub_mln(ltm_operating_expenses)
        else:
            revenue_for_cir = to_rub_mln(report.revenue)
            opex_mln = to_rub_mln(report.operating_expenses)
        if opex_mln and revenue_for_cir and revenue_for_cir > 0:
            cost_to_income = round(opex_mln / revenue_for_cir * 100, 2)
        # FCF/CAPEX для банков концептуально неприменим — оставляем None.

    if not no_leverage:
        # Стандартные показатели для промышленных компаний
        if total_liabilities_mln and equity_mln and equity_mln != 0:
            debt_to_equity = round(total_liabilities_mln / equity_mln, 2)

        if current_assets_mln and current_liabilities_mln and current_liabilities_mln != 0:
            current_ratio = round(current_assets_mln / current_liabilities_mln, 2)

    if not is_bank:
        # ─── FCF-показатели (у банка неприменимы концептуально) ──────────────
        # LTM операционный поток и CAPEX: сначала берём LTM-агрегат, затем fallback на отчёт
        ocf_raw = ltm_operating_cash_flow if ltm_operating_cash_flow is not None else getattr(report, 'operating_cash_flow', None)
        cap_raw = ltm_capex if ltm_capex is not None else getattr(report, 'capex', None)
        lease_p_raw = (
            ltm_lease_principal if ltm_lease_principal is not None
            else getattr(report, 'lease_principal', None)
        )
        lease_i_raw = (
            ltm_lease_interest if ltm_lease_interest is not None
            else getattr(report, 'lease_interest', None)
        )
        interest_paid_raw = (
            ltm_interest_paid if ltm_interest_paid is not None
            else getattr(report, 'interest_paid', None)
        )
        debt_p_raw = (
            ltm_debt_principal if ltm_debt_principal is not None
            else getattr(report, 'debt_principal', None)
        )

        ltm_ocf_mln = to_rub_mln(ocf_raw)
        cap_mln = to_rub_mln(cap_raw)
        ltm_capex_mln = cap_mln
        lease_p_mln = to_rub_mln(lease_p_raw) if lease_p_raw is not None else None
        lease_i_mln = to_rub_mln(lease_i_raw) if lease_i_raw is not None else None
        interest_paid_mln = (
            to_rub_mln(interest_paid_raw) if interest_paid_raw is not None else None
        )
        debt_p_mln = to_rub_mln(debt_p_raw) if debt_p_raw is not None else None

        if ltm_ocf_mln is not None and cap_mln is not None:
            ltm_fcf_mln = compute_fcf(
                ltm_ocf_mln,
                cap_mln,
                lease_p_mln,
                lease_i_mln,
                interest_paid_mln,
                debt_p_mln,
            )

        # ─── База для FCF-мультипликаторов ───────────────────────────────────
        # У гибрида часть операционного потока — прирост клиентских депозитов.
        # Эти деньги придётся вернуть: ими не выплатить дивиденд и не погасить
        # долг, а в год, когда приток остановится, показатель схлопнется без
        # всякого ухудшения бизнеса. Поэтому отношения считаем от потока ядра.
        # У компаний без финсегмента banking_flow=None, и база остаётся прежней.
        if ltm_fcf_mln is not None and banking_flow is not None:
            ltm_core_fcf_mln = compute_core_fcf(ltm_fcf_mln, banking_flow)
            fcf_basis = "core"
        else:
            ltm_core_fcf_mln = None
            fcf_basis = "reported"

        fcf_for_ratios = ltm_core_fcf_mln if ltm_core_fcf_mln is not None else ltm_fcf_mln

        # P/FCF = Market Cap / LTM FCF  (только если FCF > 0)
        if market_cap_full and fcf_for_ratios is not None and fcf_for_ratios > 0:
            price_to_fcf = round(market_cap_full / (fcf_for_ratios * MILLION), 2)

        # FCF / Net Income — детектор качества прибыли (только при NI > 0).
        # Безразмерное соотношение: 1.0 = FCF равен прибыли, 1.25 = FCF на 25% выше NI.
        if fcf_for_ratios is not None and net_income_mln is not None and net_income_mln > 0:
            fcf_to_net_income = round(fcf_for_ratios / net_income_mln, 4)

        if (
            net_debt_mln is not None
            and fcf_for_ratios is not None
            and fcf_for_ratios != 0
        ):
            net_debt_to_fcf = round(net_debt_mln / fcf_for_ratios, 2)

    return {
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
        "dividend_yield": dividend_yield,
        "dividend_yield_regular": dividend_yield_regular,
        "ltm_special_dividends_per_share": special_dividends_rub,
        "cost_to_income": cost_to_income,
        "market_cap": market_cap_mln,           # млн рублей
        "price_used": round(price_rub, 6) if price_rub else None,  # ₽ за акцию
        "shares_used": shares,
        # FCF (None для банков)
        "ltm_fcf": ltm_fcf_mln,
        "ltm_core_fcf": ltm_core_fcf_mln,
        # По какому потоку посчитаны P/FCF, ND/FCF и FCF/NI: "core" | "reported"
        "fcf_basis": fcf_basis,
        "ltm_operating_cash_flow": ltm_ocf_mln,
        "ltm_capex": ltm_capex_mln,
        "price_to_fcf": price_to_fcf,
        "fcf_to_net_income": fcf_to_net_income,
        "net_debt": net_debt_mln,
        "net_debt_to_fcf": net_debt_to_fcf,
    }
