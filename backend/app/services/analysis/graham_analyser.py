"""
Классификация компаний по принципам Грэма.

Поддерживает два режима:
  - "general" — промышленные компании (нефтегаз, ритейл, металлургия и т.д.)
  - "bank"    — банки и финансовые учреждения

─────────────────────────────────────────────────────────────────────────────
Почему у банков другие критерии?

Грэм формулировал свои критерии для промышленных компаний. К банкам их надо
адаптировать по двум причинам:

1. D/E (долг / капитал) у банков всегда 8–12× — это норма, а не тревожный
   сигнал. Депозиты клиентов технически являются обязательствами, поэтому
   применять порог D/E < 0.5 бессмысленно. Вместо D/E смотрим на
   Cost-to-Income (CIR) — показатель операционной эффективности.

2. Current Ratio (оборотные активы / краткосрочные обязательства) у банков
   не имеет смысла: у них нет «оборотных» и «внеоборотных» активов в
   классическом понимании. Заменяем его тем же CIR.

3. P/E банков исторически ниже промышленных — Сбербанк, ВТБ и аналоги
   традиционно торгуются при P/E 5–10, поэтому порог «недооценки» снижен.

4. P/B для банков — важнейший мультипликатор. Балансовая стоимость
   (собственный капитал) хорошо отражает реальную ценность банка, поэтому
   Грэм ценил акции банков вблизи или ниже балансовой стоимости.

Критерии для банков (адаптация Грэма):
  Недооценён:  P/E < 10, P/B < 1.2, ROE > 15%, DY > 5%, CIR < 45%
  Стабильный:  P/E 10–15, P/B < 2.0, ROE > 10%, DY > 3%, CIR < 55%
  Переоценён:  всё остальное

Критерии для промышленных компаний (оригинальный Грэм):
  Недооценён:  P/E < 15, P/B < 1.5, D/E ≤ 0.5, CR > 2.0, ROE > 15%, DY > 3%
  Стабильный:  P/E 15–25, P/B < 3.0, D/E < 1.0, CR > 1.5, ROE > 10%, DY > 3%
  Переоценён:  всё остальное
─────────────────────────────────────────────────────────────────────────────
"""


def classify_company(multipliers: dict, report_type: str = "general") -> dict:
    """
    Классифицирует компанию на основе мультипликаторов по принципам Грэма.

    Args:
        multipliers: словарь с мультипликаторами компании
        report_type: "general" (по умолчанию) или "bank"

    Returns:
        dict:
            classify           — "undervalued" | "stable" | "overvalued"
            pe_ratio_status    — "good" | "normal" | "bad"
            pb_ratio_status    — "good" | "normal" | "bad"
            debt_status        — "good" | "normal" | "bad" | "n/a" (банки)
            liquidity_status   — "good" | "normal" | "bad" | "n/a" (банки)
            profitability_status — "good" | "normal" | "bad"
            cir_status         — "good" | "normal" | "bad" | "n/a" (только банки)
    """
    if report_type == "bank":
        return _classify_bank(multipliers)
    return _classify_general(multipliers)


# ─────────────────────────────────────────────────────────────────────────────
# Промышленные компании
# ─────────────────────────────────────────────────────────────────────────────

def _classify_general(multipliers: dict) -> dict:
    pe = multipliers['pe_ratio']
    pb = multipliers['pb_ratio']
    debt_to_equity = multipliers['debt_to_equity']
    current_ratio = multipliers['current_ratio']
    roe = multipliers['roe']
    dividend_yield = multipliers['dividend_yield']

    pe_ratio_status = _evaluate_status(pe, 15, 25, is_higher_better=False)
    pb_ratio_status = _evaluate_status(pb, 1.5, 3.0, is_higher_better=False)
    debt_status = _evaluate_status(debt_to_equity, 0.5, 1.0, is_higher_better=False)
    profitability_status = _evaluate_status(roe, 15, 10, is_higher_better=True)
    liquidity_status = _evaluate_status(current_ratio, 2.0, 1.5, is_higher_better=True)

    is_undervalued = (
        pe < 15
        and pb < 1.5
        and debt_to_equity <= 0.5
        and current_ratio > 2.0
        and roe > 15
        and dividend_yield > 3
    )
    is_stable = (
        15 <= pe <= 25
        and 1.5 <= pb <= 3.0
        and debt_to_equity < 1
        and current_ratio > 1.5
        and roe > 10
        and dividend_yield > 3
    )

    classify = "undervalued" if is_undervalued else ("stable" if is_stable else "overvalued")

    return {
        "classify": classify,
        "pe_ratio_status": pe_ratio_status,
        "pb_ratio_status": pb_ratio_status,
        "debt_status": debt_status,
        "liquidity_status": liquidity_status,
        "profitability_status": profitability_status,
        "cir_status": "n/a",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Банки
# ─────────────────────────────────────────────────────────────────────────────

def _classify_bank(multipliers: dict) -> dict:
    pe = multipliers.get('pe_ratio')
    pb = multipliers.get('pb_ratio')
    roe = multipliers.get('roe')
    dividend_yield = multipliers.get('dividend_yield')
    cost_to_income = multipliers.get('cost_to_income')

    # Статусы по банковским порогам
    pe_ratio_status = _evaluate_status(pe, 10, 15, is_higher_better=False) if pe is not None else "bad"
    pb_ratio_status = _evaluate_status(pb, 1.2, 2.0, is_higher_better=False) if pb is not None else "bad"
    profitability_status = _evaluate_status(roe, 15, 10, is_higher_better=True) if roe is not None else "bad"
    # CIR: ниже — лучше (меньше расходов на единицу дохода)
    cir_status = _evaluate_status(cost_to_income, 45, 55, is_higher_better=False) if cost_to_income is not None else "n/a"

    # D/E и Current Ratio не применяются для банков
    debt_status = "n/a"
    liquidity_status = "n/a"

    # Для классификации CIR учитываем только если данные есть
    cir_ok_undervalued = (cost_to_income is not None and cost_to_income < 45) or cost_to_income is None
    cir_ok_stable = (cost_to_income is not None and cost_to_income < 55) or cost_to_income is None

    dv = dividend_yield or 0.0
    p = pe or float('inf')
    b = pb or float('inf')
    r = roe or 0.0

    is_undervalued = (
        p < 10
        and b < 1.2
        and r > 15
        and dv > 5
        and cir_ok_undervalued
    )
    is_stable = (
        10 <= p <= 15
        and b < 2.0
        and r > 10
        and dv > 3
        and cir_ok_stable
    )

    classify = "undervalued" if is_undervalued else ("stable" if is_stable else "overvalued")

    return {
        "classify": classify,
        "pe_ratio_status": pe_ratio_status,
        "pb_ratio_status": pb_ratio_status,
        "debt_status": debt_status,
        "liquidity_status": liquidity_status,
        "profitability_status": profitability_status,
        "cir_status": cir_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate_status(
    value,
    good_threshold: float,
    normal_threshold: float,
    is_higher_better: bool = True,
) -> str:
    """
    Оценивает статус показателя.

    Args:
        value: значение показателя
        good_threshold: порог для "good"
        normal_threshold: порог для "normal"
        is_higher_better: True если больше = лучше (ROE, Current Ratio)
                         False если меньше = лучше (P/E, P/B, D/E, CIR)
    """
    if value is None:
        return "bad"
    if is_higher_better:
        if value >= good_threshold:
            return "good"
        elif value >= normal_threshold:
            return "normal"
        else:
            return "bad"
    else:
        if value <= good_threshold:
            return "good"
        elif value <= normal_threshold:
            return "normal"
        else:
            return "bad"
