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


# ── Баланс и доля миноритариев ─────────────────────────────────────────────
#
# `equity` в базе — капитал акционеров материнской компании, поэтому у группы
# с миноритариями «активы = обязательства + капитал» не выполняется без их
# доли. Пока поля под неё не было, проверка гадала по величине разрыва — и у
# холдингов гадала неверно.

from app.services.analysis.data_audit import GAP, _check_balance  # noqa: E402


class FakeBalance:
    FIELDS = ("total_assets", "total_liabilities", "equity",
              "non_controlling_interest")

    def __init__(self, year=2024, **values):
        self.fiscal_year = year
        for name in self.FIELDS:
            setattr(self, name, values.get(name))


def balance(**kwargs):
    out: list = []
    _check_balance(FakeBalance(**kwargs), out)
    return out


def test_a_large_minority_stake_is_not_a_defect_when_it_is_recorded():
    """Циан за 2024 год: доля миноритариев 4 069 при капитале материнской
    5 940 — почти половина. Разрыв в 31% списать на «похоже на НКО» нельзя, и
    правильно введённый отчёт объявлялся испорченным."""
    assert balance(total_assets=13_045.0, total_liabilities=3_036.0,
                   equity=5_940.0, non_controlling_interest=4_069.0) == []


def test_without_the_stake_the_same_numbers_are_still_a_defect():
    """Поле пустое — объяснить разрыв нечем, и догадка остаётся прежней."""
    findings = balance(total_assets=13_045.0, total_liabilities=3_036.0,
                       equity=5_940.0)
    assert [f.level for f in findings] == [DEFECT]


def test_a_recorded_stake_that_still_leaves_a_gap_is_a_defect():
    """Доля разнесена, а баланс не сошёлся — гадать больше не о чем."""
    findings = balance(total_assets=13_045.0, total_liabilities=3_036.0,
                       equity=5_940.0, non_controlling_interest=1_000.0)
    assert [f.level for f in findings] == [DEFECT]
    assert "НКО" in findings[0].message


def test_negative_equity_still_balances():
    """Циан за 2020 год: капитал −872 при обязательствах 2 242."""
    assert balance(total_assets=1_370.0, total_liabilities=2_242.0,
                   equity=-872.0) == []


def test_a_small_unrecorded_stake_stays_a_soft_gap():
    """У Роснефти доля миноритариев около 5%, и поля под неё может не быть."""
    findings = balance(total_assets=100.0, total_liabilities=60.0, equity=35.0)
    assert [f.level for f in findings] == [GAP]


def test_a_zero_stake_is_not_the_same_as_an_empty_field():
    """Записанный ноль означает «миноритариев нет», и разрыв уже не спишешь."""
    findings = balance(total_assets=100.0, total_liabilities=60.0, equity=35.0,
                       non_controlling_interest=0.0)
    assert [f.level for f in findings] == [DEFECT]
