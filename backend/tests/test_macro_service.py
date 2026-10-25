"""Разбор источников раздела «Экономика» и пересчёт бюджета из накопленного итога."""
from datetime import date

from app.services.market.macro_service import (
    _month_of, budget_flows, parse_inflation, parse_reserves,
)


def test_month_of_reads_excel_serials_and_marked_text():
    assert _month_of("40544") == date(2011, 1, 1)
    assert _month_of("46266") == date(2026, 9, 1)
    # Предварительные месяцы Минфин подписывает текстом со звёздочками.
    assert _month_of("сен.26 **") == date(2026, 9, 1)
    assert _month_of("янв.23 ***") == date(2023, 1, 1)
    assert _month_of("Январь 2008¹") == date(2008, 1, 1)
    assert _month_of("Показатель") is None


def test_budget_flows_month_and_rolling_twelve():
    cumulative = [(date(2025, m, 1), 10.0 * m) for m in range(1, 13)]
    cumulative += [(date(2026, 1, 1), 12.0), (date(2026, 2, 1), 30.0)]
    month, rolling = budget_flows(cumulative)
    by_month, by_rolling = dict(month), dict(rolling)
    assert by_month[date(2025, 1, 1)] == 10.0       # январь — как есть
    assert by_month[date(2026, 2, 1)] == 18.0       # 30 − 12
    # Февраль 2026: с начала года 30 + весь 2025 (120) − январь–февраль 2025 (20).
    assert by_rolling[date(2026, 2, 1)] == 130.0
    # За 2025 год прошлого года нет — сумма за 12 месяцев не считается.
    assert date(2025, 6, 1) not in by_rolling


def test_parse_inflation_table():
    html = (
        "<table><tr><th>Дата</th></tr>"
        "<tr><td>09.2026</td><td>14,00</td><td>6,35</td><td>4,00</td></tr>"
        "<tr><td>08.2026</td><td>14,00</td><td>6,33</td><td>4,00</td></tr></table>"
    )
    out = parse_inflation(html)
    assert out["M_INFL"] == [(date(2026, 8, 1), 6.33), (date(2026, 9, 1), 6.35)]
    assert out["M_INFL_TARGET"][-1] == (date(2026, 9, 1), 4.0)


def test_parse_reserves_moves_first_of_month_to_previous_month():
    html = (
        "<tr><td>01.02.2008</td><td>488 368</td><td>475 072</td><td>474 694</td>"
        "<td>1</td><td>377</td><td>13 296</td></tr>"
    )
    out = parse_reserves(html)
    # Остаток на 1 февраля — конец января; млн $ → млрд $.
    assert out["M_RES"] == [(date(2008, 1, 1), 488.368)]
    assert out["M_RES_GOLD"] == [(date(2008, 1, 1), 13.296)]


def test_parse_credit_moves_first_of_month_to_previous_month(monkeypatch):
    from app.services.market import macro_service

    rows = [
        {"A": "Годовые темпы", "B": "46235", "C": "46266"},  # 01.08.2026, 01.09.2026
        {"A": "Денежная масса М2", "B": "13", "C": "12.8"},
        {"A": "Кредит экономике", "B": "10.5", "C": "10.4"},
        {"A": "корпоративные кредиты", "B": "13.7", "C": "13.8"},
        {"A": "корпоративные кредиты", "B": "99", "C": "99"},  # повтор ниже — не он
        {"A": "кредиты физическим лицам", "B": "6.6", "C": "6.3"},
    ]
    monkeypatch.setattr(macro_service, "_sheet_rows", lambda content, sheet: rows)
    out = macro_service.parse_credit(b"")
    assert out["M_CREDIT"] == [(date(2026, 7, 1), 10.5), (date(2026, 8, 1), 10.4)]
    assert out["M_CREDIT_CORP"][-1] == (date(2026, 8, 1), 13.8)
    assert out["M_M2"][0] == (date(2026, 7, 1), 13.0)


def test_parse_oil_rule_by_labels(monkeypatch):
    from app.services.market import macro_service

    rows = [
        {"A": "Сведения о формировании"},
        {"A": "Показатели", "B": "46235", "C": "46266"},
        {"A": "Нефтегазовые доходы, всего", "B": "424", "C": "452.4"},
        {"A": "Базовый месячный объем нефтегазовых доходов", "B": "427.8", "C": "411.4"},
        {"A": "Дополнительные нефтегазовые доходы", "B": "-3.8", "C": "41"},
        {"A": "Объем покупки (продажи) иностранной валюты и золота", "B": "55.6", "C": "279.4"},
    ]
    monkeypatch.setattr(macro_service, "_sheet_rows", lambda content, sheet: rows)
    monkeypatch.setattr(macro_service, "_sheet_names", lambda content: ["Информационное сообщение"])
    out = macro_service.parse_oil_rule(b"")
    assert out["M_OG_EXTRA"] == [(date(2026, 8, 1), -3.8), (date(2026, 9, 1), 41.0)]
    assert out["M_OG_BASE"][-1] == (date(2026, 9, 1), 411.4)
    assert out["M_FX_OPS"][-1] == (date(2026, 9, 1), 279.4)
