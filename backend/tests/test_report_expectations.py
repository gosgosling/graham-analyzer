"""
Ожидаемые отчёты и статус «что я пропустил».

Смысл модуля — не предсказать дату публикации (её не существует, пока
компания не опубликует), а найти периоды, срок по которым прошёл, а отчёта в
базе нет. Поэтому тесты проверяют границы: ровно в день срока ещё не
пропуск, на следующий — уже пропуск.
"""
from datetime import date
from types import SimpleNamespace

from app.models.enums import PeriodType
from app.services.analysis.report_expectations import (
    deadline_for,
    lag_stats,
    next_business_day,
    upcoming_reports,
    expected_periods,
    median_lag_days,
    period_end_date,
)

ANNUAL = PeriodType.ANNUAL.value
SEMI = PeriodType.SEMI_ANNUAL.value
QUART = PeriodType.QUARTERLY.value


def _rep(year, period_type=ANNUAL, quarter=None, filed=None, ends=None, rid=None):
    return SimpleNamespace(
        id=rid,
        fiscal_year=year,
        fiscal_quarter=quarter,
        period_type=period_type,
        report_date=ends or period_end_date(period_type, year, quarter),
        filing_date=filed,
    )


def _by_key(periods):
    return {p.period_key: p for p in periods}


# ─── Границы периода ───────────────────────────────────────────────────────


def test_period_end_dates():
    assert period_end_date(ANNUAL, 2025, None) == date(2025, 12, 31)
    assert period_end_date(SEMI, 2025, None) == date(2025, 6, 30)
    assert period_end_date(QUART, 2025, 1) == date(2025, 3, 31)
    assert period_end_date(QUART, 2025, 3) == date(2025, 9, 30)


# ─── Срок считается по истории самой компании ──────────────────────────────


def test_median_lag_ignores_impossible_dates():
    """Публикация раньше отчётной даты — опечатка в годе, а не быстрый отчёт."""
    reports = [
        _rep(2023, filed=date(2024, 4, 20)),   # +111
        _rep(2024, filed=date(2025, 4, 10)),   # +100
        _rep(2022, filed=date(2022, 3, 24)),   # −282, битая
    ]

    assert median_lag_days(reports, ANNUAL) == 105


def test_deadline_uses_own_history_with_margin():
    """Компания стабильно публикует на 100-й день — срок 100 + запас 30."""
    reports = [
        _rep(2023, filed=date(2024, 4, 9)),
        _rep(2024, filed=date(2025, 4, 10)),
    ]

    assert deadline_for(reports, ANNUAL, date(2025, 12, 31)) == date(2026, 5, 10)


def test_deadline_falls_back_without_history():
    """Без своих дат берём верхнюю границу распределения по всей базе."""
    reports = [_rep(2024)]

    assert deadline_for(reports, ANNUAL, date(2025, 12, 31)) == date(2026, 4, 30)
    assert deadline_for(reports, SEMI, date(2026, 6, 30)) == date(2026, 8, 29)


# ─── Три состояния ─────────────────────────────────────────────────────────


def test_filed_window_open_and_overdue():
    reports = [_rep(2023, rid=1), _rep(2024, rid=2)]
    periods = _by_key(expected_periods(reports, today=date(2026, 3, 1)))

    assert periods["2023"].status == "filed"
    assert periods["2023"].report_id == 1
    # 2025 закончился, срок по умолчанию до 30 апреля 2026 — ещё не пропуск
    assert periods["2025"].status == "window_open"
    assert periods["2025"].days_overdue is None


def test_overdue_counts_days():
    reports = [_rep(2023, rid=1)]
    periods = _by_key(expected_periods(reports, today=date(2026, 5, 10)))

    assert periods["2024"].status == "overdue"
    assert periods["2024"].deadline == date(2025, 4, 30)
    assert periods["2024"].days_overdue == 375


def test_deadline_day_itself_is_not_overdue():
    """Ровно в день срока отчёт ещё могут опубликовать."""
    reports = [_rep(2023, rid=1)]
    on_deadline = _by_key(expected_periods(reports, today=date(2025, 4, 30)))
    next_day = _by_key(expected_periods(reports, today=date(2025, 5, 1)))

    assert on_deadline["2024"].status == "window_open"
    assert next_day["2024"].status == "overdue"
    assert next_day["2024"].days_overdue == 1


# ─── Ожидаем только то, что компания реально сдаёт ─────────────────────────


def test_quarterly_not_expected_from_company_that_never_files_them():
    """Квартальные МСФО не обязательны — ждать их от всех значит врать."""
    reports = [_rep(2023, rid=1), _rep(2024, rid=2)]
    kinds = {p.period_type for p in expected_periods(reports, today=date(2026, 3, 1))}

    assert kinds == {ANNUAL}


def test_semi_annual_expected_when_company_files_them():
    reports = [
        _rep(2024, rid=1),
        _rep(2025, SEMI, rid=2),
    ]
    periods = _by_key(expected_periods(reports, today=date(2026, 9, 1)))

    assert "2026H1" in periods
    assert periods["2026H1"].status in {"window_open", "overdue"}
    assert periods["2025H1"].status == "filed"


def test_abandoned_interims_stop_being_expected():
    """Перестала сдавать полугодовые три года назад — больше не ждём."""
    reports = [_rep(2020, SEMI, rid=1), _rep(2024, rid=2), _rep(2025, rid=3)]
    kinds = {p.period_type for p in expected_periods(reports, today=date(2026, 8, 16))}

    assert SEMI not in kinds


# ─── Крайние случаи ────────────────────────────────────────────────────────


def test_unfinished_period_is_not_expected():
    """Год ещё идёт — отчёта за него быть не может."""
    reports = [_rep(2024, rid=1)]
    years = {p.fiscal_year for p in expected_periods(reports, today=date(2026, 6, 1))}

    assert 2026 not in years


def test_no_reports_gives_nothing():
    assert expected_periods([], today=date(2026, 3, 1)) == []


def test_history_starts_from_first_report_year():
    """До первого отчёта компании в базе не было — назад не заглядываем."""
    reports = [_rep(2022, rid=1)]
    years = sorted(p.fiscal_year for p in expected_periods(reports, today=date(2026, 3, 1)))

    assert years == [2022, 2023, 2024, 2025]


# ─── Прогноз будущих публикаций ────────────────────────────────────────────
#
# Точной даты не существует, поэтому проверяется не «угадали», а честность:
# перенос на рабочий день и признание собственной неточности.


def test_weekend_forecast_moves_to_monday():
    """Ни одна компания не публикует отчётность в субботу."""
    assert next_business_day(date(2026, 8, 22)) == date(2026, 8, 24)  # сб → пн
    assert next_business_day(date(2026, 8, 23)) == date(2026, 8, 24)  # вс → пн
    assert next_business_day(date(2026, 8, 21)) == date(2026, 8, 21)  # пт остаётся


def test_lag_stats_returns_median_spread_and_count():
    reports = [
        _rep(2022, filed=date(2023, 4, 10)),   # +100
        _rep(2023, filed=date(2024, 4, 14)),   # +105
        _rep(2024, filed=date(2025, 4, 20)),   # +110
    ]

    median, spread, samples = lag_stats(reports, ANNUAL)

    assert (median, spread, samples) == (105, 10, 3)


def test_narrow_spread_gives_confident_forecast():
    """Публикует день в день — прогноз можно называть датой."""
    reports = [
        _rep(2023, SEMI, filed=date(2023, 8, 20)),
        _rep(2024, SEMI, filed=date(2024, 8, 22)),
        _rep(2025, SEMI, filed=date(2025, 8, 21)),
        _rep(2025, rid=1),
    ]
    upcoming = {u.period_key: u for u in upcoming_reports(reports, today=date(2026, 8, 16))}

    h1 = upcoming["2026H1"]
    assert h1.confidence == "narrow"
    assert h1.expected_date.weekday() < 5


def test_wide_spread_is_admitted():
    """Разброс в полтора месяца — прогноз не имеет права выглядеть точным."""
    reports = [
        _rep(2022, filed=date(2023, 3, 1)),
        _rep(2023, filed=date(2024, 4, 25)),
        _rep(2024, filed=date(2025, 3, 10)),
    ]
    # Горизонт длиннее: годовой отчёт за 2026 выйдет весной 2027-го
    upcoming = {
        u.period_key: u
        for u in upcoming_reports(reports, today=date(2026, 8, 16), horizon_days=300)
    }

    assert upcoming["2026"].confidence == "rough"


def test_no_history_still_forecasts_from_deadline():
    """Первый отчёт компании: своей привычки нет, берём общий срок."""
    reports = [_rep(2025, rid=1)]
    upcoming = {
        u.period_key: u
        for u in upcoming_reports(reports, today=date(2026, 8, 16), horizon_days=300)
    }

    assert upcoming["2026"].confidence == "rough"
    assert upcoming["2026"].lag_days == 120


def test_far_future_report_is_outside_default_horizon():
    """Годовой за текущий год выйдет весной — в календарь на полгода не лезет."""
    reports = [_rep(2025, rid=1)]
    keys = {u.period_key for u in upcoming_reports(reports, today=date(2026, 8, 16))}

    assert "2026" not in keys


def test_already_filed_period_not_in_calendar():
    reports = [_rep(2025, rid=1), _rep(2026, SEMI, rid=2), _rep(2025, SEMI, rid=3)]
    keys = {u.period_key for u in upcoming_reports(reports, today=date(2026, 8, 16))}

    assert "2026H1" not in keys


def test_horizon_limits_the_calendar():
    reports = [_rep(2025, rid=1)]
    short = upcoming_reports(reports, today=date(2026, 8, 16), horizon_days=30)
    long = upcoming_reports(reports, today=date(2026, 8, 16), horizon_days=300)

    assert len(short) < len(long)
