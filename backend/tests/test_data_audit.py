"""Аудит данных: где отрицательная величина — поломка, а где событие.

Здесь проверяется одно правило из многих — то, которое различает банк и
промышленную компанию. Оно стоит отдельного теста, потому что ошибка в нём
не видна: компания просто молча исчезает из экрана, и понять, что её выкинуло
правило, написанное не про неё, можно только заглянув в аудит.
"""

from app.services.analysis.data_audit import DEFECT, SUSPECT, _check_ranges


class FakeReport:
    """Отчёт — ровно те поля, которые читает проверка диапазонов."""

    FIELDS = ("revenue", "total_assets", "gross_loans", "customer_deposits",
              "equity", "current_assets")

    def __init__(self, year=2022, report_type="general", **values):
        self.fiscal_year = year
        self.report_type = report_type
        for name in self.FIELDS:
            setattr(self, name, values.get(name))


def check(**kwargs):
    out: list = []
    _check_ranges(FakeReport(**kwargs), out)
    return out


def levels(findings, name):
    return [f.level for f in findings if name in f.message]


# ── Выручка ────────────────────────────────────────────────────────────────

def test_negative_revenue_is_a_defect_for_an_ordinary_company():
    """Валовые продажи отрицательными не бывают — это испорченная строка."""
    assert levels(check(revenue=-501_100.0), "revenue") == [DEFECT]


def test_negative_revenue_is_only_suspect_for_a_bank():
    """Случай ВТБ за 2022 год: операционный доход −501 млрд.

    У кредитной организации «выручка» — величина чистая: проценты полученные
    минус уплаченные, плюс комиссии, плюс результат по торговле. В плохой год
    она законно уходит в минус, и объявлять это поломкой значит выкинуть
    компанию из экрана за то, что с ней действительно случилось.
    """
    assert levels(check(revenue=-501_100.0, report_type="bank"), "revenue") == [SUSPECT]


def test_positive_revenue_raises_nothing():
    assert check(revenue=1_083_800.0, report_type="bank") == []


# ── Остатки ────────────────────────────────────────────────────────────────

def test_balances_cannot_be_negative_even_for_a_bank():
    """Послабление касается только сальдо. Портфель, депозиты и активы —
    остатки, и минус в них означает поломку у кого угодно."""
    findings = check(report_type="bank", gross_loans=-1.0,
                     customer_deposits=-1.0, total_assets=-1.0)
    assert {f.level for f in findings} == {DEFECT}
    assert len(findings) == 3


def test_negative_equity_stays_soft_for_everyone():
    """Отрицательный капитал — положение дел, а не опечатка: у Озона он
    ушёл в минус по-настоящему."""
    assert levels(check(equity=-79_718.0), "equity") == [SUSPECT]
    assert levels(check(equity=-79_718.0, report_type="bank"), "equity") == [SUSPECT]
