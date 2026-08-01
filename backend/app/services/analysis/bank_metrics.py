"""Показатели банка: риск, качество активов, фондирование, капитал.

Классические мультипликаторы отвечают на вопрос «сколько стоит» и «сколько
зарабатывает». У банка этого мало: он умирает не от дорогой оценки, а от
собственных кредитов. Здесь считается вторая половина — во что обходится риск,
чем банк фондируется и сколько у него запаса по капиталу.

Все показатели — отношения величин из одного отчёта, поэтому валюта
сокращается и конвертация в рубли не нужна. Балансовые знаменатели берутся на
конец периода: усреднение с прошлым годом требует соседнего отчёта, а функция
намеренно работает с одним и остаётся чистой.

Пороговые значения — под российский рынок, каждый с обоснованием в
`_BANDS`. Они не из книги Грэма: банки он выносил за скобки защитного набора.
Ближе всего сюда подход Баффета — дешёвое фондирование, устойчивый ROE,
консервативное резервирование, — и он положен в основу порогов.
"""
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

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
    net_loans: Optional[float] = None               # Портфель за вычетом резерва, млн

    def as_dict(self) -> Dict[str, Optional[float]]:
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
}

# Показатели без светофора: смысл зависит от фазы ставочного цикла.
_INFORMATIONAL = (
    "cost_of_funding",
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


def compute_bank_metrics(report: Any) -> BankMetrics:
    """Считает банковские показатели по одному отчёту.

    Args:
        report: объект с атрибутами отчёта (ORM-модель или заглушка в тестах).

    Returns:
        BankMetrics — незаполненные поля остаются None, чтобы интерфейс мог
        показать прочерк вместо правдоподобного нуля.
    """
    gross_loans = _num(getattr(report, "gross_loans", None))
    allowance = _num(getattr(report, "loan_loss_allowance", None))

    net_loans: Optional[float] = None
    if gross_loans is not None:
        net_loans = round(gross_loans - allowance, 3) if allowance is not None else gross_loans

    return BankMetrics(
        roa=_ratio_pct(getattr(report, "net_income", None), getattr(report, "total_assets", None)),
        net_interest_margin=_ratio_pct(
            getattr(report, "net_interest_income", None),
            getattr(report, "total_assets", None),
        ),
        cost_of_risk=_ratio_pct(getattr(report, "provisions", None), gross_loans),
        npl_ratio=_ratio_pct(getattr(report, "npl_loans", None), gross_loans),
        npl_coverage=_ratio_pct(allowance, getattr(report, "npl_loans", None)),
        loans_to_deposits=_ratio_pct(net_loans, getattr(report, "customer_deposits", None)),
        cost_of_funding=_ratio_pct(
            getattr(report, "interest_expense", None),
            getattr(report, "customer_deposits", None),
        ),
        capital_adequacy_ratio=_num(getattr(report, "capital_adequacy_ratio", None)),
        capital_adequacy_core=_num(getattr(report, "capital_adequacy_core", None)),
        retail_loans_share=_ratio_pct(getattr(report, "loans_retail", None), gross_loans),
        retail_deposits_share=_ratio_pct(
            getattr(report, "deposits_retail", None),
            getattr(report, "customer_deposits", None),
        ),
        capital_to_rwa=_ratio_pct(
            getattr(report, "equity", None),
            getattr(report, "risk_weighted_assets", None),
        ),
        net_loans=net_loans,
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
    """Светофор по всем показателям сразу."""
    return {name: evaluate_bank_metric(name, value) for name, value in metrics.as_dict().items()}
