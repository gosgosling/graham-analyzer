"""Покрытие процентов: во сколько раз операционная прибыль больше процентов.

У Грэма это один из тестов финансовой устойчивости: компания должна
зарабатывать проценты по долгу с большим запасом, иначе любой спад делает
её заложником кредиторов. Для холдинга это вообще единственный показатель
его собственной жизнеспособности — своих операций у него нет, а долг центра
обслуживать надо.

У АФК «Система» за 2025 год: операционная прибыль 133 950 млн при финансовых
расходах 390 298 млн — покрытие 0,34. Проценты втрое больше того, что
зарабатывает вся группа.
"""
from typing import Any, Optional

Status = str  # 'good' | 'normal' | 'bad' | 'n/a'

# Грэм требовал от защитного инвестора пятикратного запаса; двукратный —
# граница, ниже которой обслуживание долга становится вопросом выживания.
_GOOD = 5.0
_NORMAL = 2.0

COVERAGE_HINT = "≥ 5× — запас по Грэму; < 2× — долг диктует условия"


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_interest_coverage(report: Any) -> Optional[float]:
    """Операционная прибыль ÷ финансовые расходы, разы.

    Returns:
        None, если нет одной из величин или процентов не было вовсе.
        Отрицательное значение при операционном убытке возвращается как есть:
        это честный сигнал, а не повод прятать показатель.
    """
    operating_profit = _num(getattr(report, "operating_profit", None))
    finance_costs = _num(getattr(report, "finance_costs", None))

    if operating_profit is None or finance_costs is None:
        return None
    if finance_costs <= 0:
        return None

    return round(operating_profit / finance_costs, 2)


def evaluate_interest_coverage(value: Optional[float]) -> Status:
    if value is None:
        return "n/a"
    if value >= _GOOD:
        return "good"
    return "normal" if value >= _NORMAL else "bad"
