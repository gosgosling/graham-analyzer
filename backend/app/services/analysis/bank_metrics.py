"""Показатели банка: риск, качество активов, фондирование, капитал.

Классические мультипликаторы отвечают на вопрос «сколько стоит» и «сколько
зарабатывает». У банка этого мало: он умирает не от дорогой оценки, а от
собственных кредитов. Здесь считается вторая половина — во что обходится риск,
чем банк фондируется и сколько у него запаса по капиталу.

Все показатели — отношения величин из одного отчёта, поэтому валюта
сокращается и конвертация в рубли не нужна. Балансовые знаменатели берутся на
конец периода: усреднение с прошлым годом требует соседнего отчёта, а функция
намеренно работает с одним и остаётся чистой.

Потоковые числители (прибыль, процентный доход, резервы, процентные расходы)
приводятся к году: у полугодового отчёта в числителе половина года, а в
знаменателе полный баланс, и без приведения ROA полугодия вдвое ниже годового
при том же качестве работы. Множитель берётся из `periods.py`.

Пороговые значения — под российский рынок, каждый с обоснованием в
`_BANDS`. Они не из книги Грэма: банки он выносил за скобки защитного набора.
Ближе всего сюда подход Баффета — дешёвое фондирование, устойчивый ROE,
консервативное резервирование, — и он положен в основу порогов.
"""
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

from app.services.analysis.periods import annualization_factor

Status = str  # 'good' | 'normal' | 'bad' | 'n/a'


@dataclass(frozen=True)
class BankMetrics:
    """Рассчитанные показатели банка. None означает «нет данных для расчёта»."""

    roa: Optional[float] = None                     # Прибыль / активы, %
    net_interest_margin: Optional[float] = None     # ЧПД / активы, %
    cost_of_risk: Optional[float] = None            # Резерв за период / портфель, %
    npl_ratio: Optional[float] = None               # Обесцененные / портфель, %
    npl_coverage: Optional[float] = None            # Накопленный резерв / обесцененные, %
    loans_to_deposits: Optional[float] = None       # Чистые кредиты / средства клиентов, %
    cost_of_funding: Optional[float] = None         # Процентные расходы / средства клиентов, %
    capital_adequacy_ratio: Optional[float] = None  # Н1.0 общий, как раскрыл эмитент, %
    capital_adequacy_core: Optional[float] = None   # Н1.1 / CET1 — основной капитал, %
    capital_to_rwa: Optional[float] = None          # Капитал / RWA, % — сверка с Н1.0
    retail_loans_share: Optional[float] = None      # Доля розницы в портфеле, %
    retail_deposits_share: Optional[float] = None   # Доля физлиц в средствах клиентов, %
    funding_spread: Optional[float] = None          # Стоимость фондирования − ключевая ставка, п.п.
    key_rate: Optional[float] = None                # Средняя ключевая ставка за период, %
    net_loans: Optional[float] = None               # Портфель за вычетом резерва, млн
    # Откуда взяты потоки: 'ltm' — фактические 12 месяцев, 'annualised' —
    # период умножен на 12/длину, 'reported' — годовой отчёт как есть.
    # Интерфейс подписывает этим период, чтобы удвоение полугодия не выдавалось
    # за факт.
    flow_basis: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


# метрика → (порог «хорошо», порог «нормально», больше — лучше?, пояснение)
_BANDS: Dict[str, Tuple[Optional[float], Optional[float], bool, str]] = {
    # ROA важнее ROE: ROE легко поднять плечом, ROA — только качеством работы.
    "roa": (2.0, 1.0, True, "≥ 2% — сильный банк; < 1% — слабая отдача активов"),
    "net_interest_margin": (4.5, 3.0, True, "к активам; ниже 3% — тонкая маржа"),
    # Стоимость риска: сколько процентов портфеля банк ежегодно списывает.
    "cost_of_risk": (1.0, 2.0, False, "≤ 1% — норма цикла; > 2% — портфель ухудшается"),
    "npl_ratio": (4.0, 8.0, False, "≤ 4% — здоровый портфель"),
    "npl_coverage": (100.0, 70.0, True, "≥ 100% — проблемные кредиты покрыты резервом"),
    # Кредиты сверх депозитов финансируются рынком — дороже и капризнее.
    "loans_to_deposits": (100.0, 120.0, False, "≤ 100% — кредиты покрыты депозитами"),
    # Н1.0: минимум ЦБ 8% плюс надбавки; ниже 10% банк ограничен в дивидендах.
    "capital_adequacy_ratio": (12.0, 10.0, True, "≥ 12% — запас есть; < 10% — риск"),
    # Основной капитал поглощает убытки первым: общий норматив включает
    # субординированные займы, которые списываются не сразу и не всегда.
    "capital_adequacy_core": (10.0, 8.0, True, "Н1.1/CET1: ≥ 10% — прочно; < 8% — тонко"),
    # Спред к ключевой ставке: во сколько банку обходятся деньги ОТНОСИТЕЛЬНО
    # рынка. Дешёвое фондирование — то самое преимущество, которое Баффет
    # ценил в банках выше прочего: заработать на активах может каждый,
    # привлечь дешевле конкурентов — единицы. Меньше (отрицательнее) — лучше.
    "funding_spread": (-3.0, 0.0, False, "на 3+ п.п. ниже ключевой — сильное преимущество; выше ставки — тревога"),
}

# Показатели без светофора: смысл зависит от фазы ставочного цикла.
_INFORMATIONAL = (
    "cost_of_funding",
    "key_rate",
    "capital_to_rwa",
    "net_loans",
    # Доля розницы — не «хорошо/плохо», а профиль банка: розничные депозиты
    # дешевле и устойчивее, розничные кредиты доходнее и рискованнее.
    "retail_loans_share",
    "retail_deposits_share",
)


def _num(value: Any) -> Optional[float]:
    """Numeric из БД приходит Decimal; None и нечисловое — отсутствие данных."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_pct(numerator: Any, denominator: Any) -> Optional[float]:
    """Отношение в процентах. Нулевой знаменатель — не ноль, а отсутствие смысла."""
    num, den = _num(numerator), _num(denominator)
    if num is None or den is None or den == 0:
        return None
    return round(num / den * 100, 2)


# Потоковые величины: их нельзя делить на баланс, не приведя к году.
_FLOW_ATTRS = ("net_income", "net_interest_income", "provisions", "interest_expense")


def _year_flows(
    report: Any,
    ltm_flows: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Optional[float]], str]:
    """Годовые значения потоков и признак того, откуда они взялись.

    Порядок предпочтения:
      1. LTM — фактические двенадцать месяцев, собранные из трёх отчётов.
         Ничего не предполагается, поэтому это основной путь.
      2. Приведение к году множителем 12/длину периода. Запасной путь: он
         допускает, что оставшиеся месяцы будут как прошедшие, и годится
         только когда прошлогоднего промежуточного отчёта нет и LTM не собрать.
      3. Годовой отчёт — значения как есть, множитель равен единице.
    """
    factor = annualization_factor(report)
    basis = "reported" if factor == 1.0 else "annualised"

    flows: Dict[str, Optional[float]] = {}
    for attr in _FLOW_ATTRS:
        ltm = _num((ltm_flows or {}).get(attr))
        if ltm is not None:
            flows[attr] = ltm
            basis = "ltm"
            continue
        value = _num(getattr(report, attr, None))
        flows[attr] = value * factor if value is not None else None

    return flows, basis


def compute_bank_metrics(
    report: Any,
    key_rate: Optional[float] = None,
    ltm_flows: Optional[Dict[str, Any]] = None,
) -> BankMetrics:
    """Считает банковские показатели по одному отчёту.

    Args:
        report: объект с атрибутами отчёта (ORM-модель или заглушка в тестах).
            Балансовые величины всегда берутся отсюда — на отчётную дату.
        key_rate: средняя ключевая ставка ЦБ за период отчёта, %. Без неё
            спред к ставке не считается: сравнивать стоимость фондирования
            с сегодняшней ставкой для отчёта трёхлетней давности бессмысленно.
        ltm_flows: потоки за последние двенадцать месяцев в валюте отчёта —
            прибыль, процентный доход, резервы, процентные расходы. Если
            переданы, считаем по ним: это факт, а не экстраполяция полугодия.

    Returns:
        BankMetrics — незаполненные поля остаются None, чтобы интерфейс мог
        показать прочерк вместо правдоподобного нуля.
    """
    gross_loans = _num(getattr(report, "gross_loans", None))
    allowance = _num(getattr(report, "loan_loss_allowance", None))

    flows, flow_basis = _year_flows(report, ltm_flows)

    cost_of_funding = _ratio_pct(
        flows["interest_expense"],
        getattr(report, "customer_deposits", None),
    )

    net_loans: Optional[float] = None
    if gross_loans is not None:
        net_loans = round(gross_loans - allowance, 3) if allowance is not None else gross_loans

    return BankMetrics(
        roa=_ratio_pct(flows["net_income"], getattr(report, "total_assets", None)),
        net_interest_margin=_ratio_pct(
            flows["net_interest_income"],
            getattr(report, "total_assets", None),
        ),
        cost_of_risk=_ratio_pct(flows["provisions"], gross_loans),
        npl_ratio=_ratio_pct(getattr(report, "npl_loans", None), gross_loans),
        npl_coverage=_ratio_pct(allowance, getattr(report, "npl_loans", None)),
        loans_to_deposits=_ratio_pct(net_loans, getattr(report, "customer_deposits", None)),
        cost_of_funding=cost_of_funding,
        capital_adequacy_ratio=_num(getattr(report, "capital_adequacy_ratio", None)),
        capital_adequacy_core=_num(getattr(report, "capital_adequacy_core", None)),
        retail_loans_share=_ratio_pct(getattr(report, "loans_retail", None), gross_loans),
        retail_deposits_share=_ratio_pct(
            getattr(report, "deposits_retail", None),
            getattr(report, "customer_deposits", None),
        ),
        funding_spread=(
            round(cost_of_funding - key_rate, 2)
            if cost_of_funding is not None and key_rate is not None
            else None
        ),
        key_rate=_num(key_rate),
        capital_to_rwa=_ratio_pct(
            getattr(report, "equity", None),
            getattr(report, "risk_weighted_assets", None),
        ),
        net_loans=net_loans,
        flow_basis=flow_basis,
    )


def evaluate_bank_metric(name: str, value: Optional[float]) -> Status:
    """Светофор по одному показателю.

    Возвращает 'n/a' и для незаполненных значений, и для справочных
    показателей: у стоимости фондирования нет «хорошего» уровня в отрыве от
    ключевой ставки, и красить её в красный было бы враньём.
    """
    if value is None or name in _INFORMATIONAL:
        return "n/a"
    band = _BANDS.get(name)
    if band is None:
        return "n/a"

    good, normal, higher_is_better, _hint = band
    if good is None or normal is None:
        return "n/a"

    if higher_is_better:
        if value >= good:
            return "good"
        return "normal" if value >= normal else "bad"

    if value <= good:
        return "good"
    return "normal" if value <= normal else "bad"


def bank_metric_hint(name: str) -> Optional[str]:
    """Пояснение к порогу — то же, что видит аналитик в подсказке интерфейса."""
    band = _BANDS.get(name)
    return band[3] if band else None


def evaluate_all(metrics: BankMetrics) -> Dict[str, Status]:
    """Светофор по всем показателям сразу.

    `flow_basis` — служебная пометка, а не показатель: у неё нет ни значения,
    ни порога, и в словаре статусов ей делать нечего.
    """
    return {
        name: evaluate_bank_metric(name, value)
        for name, value in metrics.as_dict().items()
        if name != "flow_basis"
    }
