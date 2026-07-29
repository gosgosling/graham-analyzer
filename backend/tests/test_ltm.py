"""LTM-агрегация потоковых показателей — без базы данных.

Формула для промежуточного отчёта:
    LTM = FY_{N-1} + YTD_N − YTD_{N-1}

Пример: полугодие 2026 + год 2025 − полугодие 2025 → июль 2025 … июнь 2026.

`get_ltm_data` ходит в Postgres, поэтому здесь тестируются чистые хелперы,
из которых она собирается. Отчёт — SimpleNamespace с нужными атрибутами.
"""
from types import SimpleNamespace

from app.services.analysis.multiplier_service import (
    _field_rub,
    _flow_to_ltm_payload,
    _interim_ltm_source_label,
    _ltm_back_to_report_currency,
    _ltm_formula_field,
    _ltm_from_interim_formula,
)
from app.models.enums import PeriodType


def _rpt(**kw) -> SimpleNamespace:
    base = {
        "currency": "RUB",
        "exchange_rate": None,
        "dividends_paid": True,
        "net_income": None,
        "revenue": None,
        "dividends_per_share": None,
        "special_dividends_per_share": None,
        "operating_cash_flow": None,
        "capex": None,
        "lease_principal": None,
        "lease_interest": None,
        "interest_paid": None,
        "debt_principal": None,
        "period_type": PeriodType.ANNUAL,
        "fiscal_quarter": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ─── Формула LTM = FY + текущий YTD − прошлый YTD ───────────────────────────


def test_h1_ltm_classic_example():
    """H1_2026=40, FY_2025=100, H1_2025=45 → LTM = 40 + 100 − 45 = 95."""
    current = _rpt(net_income=40_000)
    prior_fy = _rpt(net_income=100_000)
    prior_ytd = _rpt(net_income=45_000)

    assert _ltm_formula_field(current, prior_fy, prior_ytd, "net_income") == 95_000.0


def test_ltm_formula_returns_none_if_any_piece_missing():
    """Неполная тройка — не угадываем, а честно отдаём None."""
    current = _rpt(net_income=40_000)
    prior_fy = _rpt(net_income=100_000)
    prior_ytd = _rpt(net_income=None)

    assert _ltm_formula_field(current, prior_fy, prior_ytd, "net_income") is None


def test_ltm_from_interim_applies_formula_to_all_flow_fields():
    current = _rpt(
        net_income=40, revenue=400, operating_cash_flow=50, capex=10,
        dividends_per_share=6, special_dividends_per_share=2,
    )
    prior_fy = _rpt(
        net_income=100, revenue=1000, operating_cash_flow=120, capex=30,
        dividends_per_share=10, special_dividends_per_share=0,
    )
    prior_ytd = _rpt(
        net_income=45, revenue=450, operating_cash_flow=55, capex=12,
        dividends_per_share=4, special_dividends_per_share=1,
    )

    flow = _ltm_from_interim_formula(
        current, prior_fy, prior_ytd,
        ("net_income", "revenue", "operating_cash_flow", "capex",
         "dividends_per_share", "special_dividends_per_share"),
    )

    assert flow["net_income"] == 95.0
    assert flow["revenue"] == 950.0
    assert flow["operating_cash_flow"] == 115.0
    assert flow["capex"] == 28.0
    assert flow["dividends_per_share"] == 12.0  # 6 + 10 − 4
    assert flow["special_dividends_per_share"] == 1.0  # 2 + 0 − 1


def test_ltm_can_be_negative_when_earnings_collapse():
    """Убыток текущего периода сильнее прошлогодней прибыли — LTM отрицательный."""
    assert _ltm_formula_field(
        _rpt(net_income=-80),
        _rpt(net_income=100),
        _rpt(net_income=60),
        "net_income",
    ) == -40.0


# ─── Дивиденды и конвертация ────────────────────────────────────────────────


def test_dividends_ignored_when_not_paid():
    """Сумма в поле есть, но дивиденды не платили — в LTM не входит."""
    report = _rpt(dividends_paid=False, dividends_per_share=20.0)

    assert _field_rub(report, "dividends_per_share") is None
    assert _field_rub(report, "special_dividends_per_share") is None


def test_ltm_formula_with_usd_reports():
    """Все три отчёта в USD — формула считается уже в рублях."""
    current = _rpt(currency="USD", exchange_rate=100.0, net_income=40)
    prior_fy = _rpt(currency="USD", exchange_rate=90.0, net_income=100)
    prior_ytd = _rpt(currency="USD", exchange_rate=95.0, net_income=45)

    # 40*100 + 100*90 − 45*95 = 4000 + 9000 − 4275 = 8725
    assert _ltm_formula_field(current, prior_fy, prior_ytd, "net_income") == 8725.0


# ─── Обратная конвертация перед calc_multipliers ────────────────────────────


def test_ltm_back_to_rub_report_is_identity():
    report = _rpt(currency="RUB")
    assert _ltm_back_to_report_currency(95_000.0, report) == 95_000.0


def test_ltm_back_to_usd_divides_by_rate():
    """LTM уже в рублях; calc_multipliers умножит снова — откатываем делением."""
    report = _rpt(currency="USD", exchange_rate=90.0)

    assert _ltm_back_to_report_currency(9_000.0, report) == 100.0


def test_ltm_back_without_rate_keeps_rub_value():
    report = _rpt(currency="USD", exchange_rate=None)
    assert _ltm_back_to_report_currency(9_000.0, report) == 9_000.0


# ─── Служебные преобразования ───────────────────────────────────────────────


def test_flow_to_ltm_payload_renames_keys():
    payload = _flow_to_ltm_payload({"net_income": 95.0, "capex": 28.0, "revenue": None})

    assert payload["ltm_net_income"] == 95.0
    assert payload["ltm_capex"] == 28.0
    assert payload["ltm_revenue"] is None
    assert "net_income" not in payload


def test_interim_source_label():
    assert _interim_ltm_source_label(
        _rpt(period_type=PeriodType.SEMI_ANNUAL)
    ) == "semi_annual_derived"
    assert _interim_ltm_source_label(
        _rpt(period_type=PeriodType.QUARTERLY, fiscal_quarter=2)
    ) == "quarterly_2_derived"
