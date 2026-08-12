"""Пересчёт количества акций на отчётную дату при дроблениях."""

from datetime import date

import pytest

from app.services.share_splits import (
    KNOWN_SPLITS,
    normalize_splits,
    price_scale_hint,
    seed_splits,
    shares_at_date,
    shares_factor,
)

# МКПАО «Т-Технологии»: дробление 10:1 17 апреля 2026 года
TCS = [{"date": "2026-04-17", "ratio": 10}]


def test_split_after_report_date_scales_shares_down():
    """Отчёт за 2025 год: в реестре сегодня 2,68 млрд, тогда было 268 млн."""
    assert shares_at_date(2_682_747_860, TCS, date(2025, 12, 31)) == 268_274_786


def test_split_before_report_date_changes_nothing():
    """Дробление уже отражено в отчёте — трогать нельзя."""
    assert shares_at_date(2_682_747_860, TCS, date(2026, 12, 31)) == 2_682_747_860


def test_split_day_itself_is_already_new_scale():
    assert shares_factor(TCS, date(2026, 4, 17)) == 1.0
    assert shares_factor(TCS, date(2026, 4, 16)) == 10.0


def test_two_splits_multiply():
    splits = [{"date": "2020-01-01", "ratio": 2}, {"date": "2026-04-17", "ratio": 10}]
    assert shares_factor(splits, date(2019, 12, 31)) == 20.0
    assert shares_factor(splits, date(2021, 1, 1)) == 10.0
    assert shares_factor(splits, date(2026, 5, 1)) == 1.0


def test_reverse_split_scales_shares_up():
    """Консолидация 1:10 — тогда акций было в 10 раз больше."""
    consolidation = [{"date": "2024-01-15", "ratio": 0.1}]
    assert shares_at_date(1_000_000, consolidation, date(2023, 12, 31)) == 10_000_000


def test_no_splits_returns_input_unchanged():
    assert shares_at_date(1_000, None, date(2020, 1, 1)) == 1_000
    assert shares_at_date(1_000, [], date(2020, 1, 1)) == 1_000
    assert shares_factor(None, date(2020, 1, 1)) == 1.0


def test_unknown_date_does_not_guess():
    """Без отчётной даты неизвестно, какая шкала нужна — оставляем как есть."""
    assert shares_at_date(2_682_747_860, TCS, None) == 2_682_747_860
    assert shares_factor(TCS, None) == 1.0


def test_missing_issuesize_stays_missing():
    assert shares_at_date(None, TCS, date(2025, 12, 31)) is None


@pytest.mark.parametrize(
    "broken",
    [
        [{"date": "не дата", "ratio": 10}],
        [{"date": "2026-04-17", "ratio": "много"}],
        [{"date": "2026-04-17", "ratio": 0}],      # делить на ноль нельзя
        [{"date": "2026-04-17", "ratio": -2}],
        [{"ratio": 10}],
        ["мусор", None, 42],
        "вообще не список",
    ],
)
def test_broken_entries_are_ignored(broken):
    assert normalize_splits(broken) == []
    assert shares_at_date(1_000, broken, date(2020, 1, 1)) == 1_000


def test_order_in_storage_does_not_matter():
    splits = [{"date": "2026-04-17", "ratio": 10}, {"date": "2020-01-01", "ratio": 2}]
    assert shares_factor(splits, date(2019, 12, 31)) == 20.0


def test_normalize_accepts_date_objects():
    assert normalize_splits([{"date": date(2026, 4, 17), "ratio": 10}]) == [
        {"date": "2026-04-17", "ratio": 10.0}
    ]


def test_hint_explains_scale_change():
    hint = price_scale_hint(TCS, date(2025, 12, 31))
    assert hint is not None
    assert "дробление 10:1" in hint
    assert "2026-04-17" in hint


def test_hint_says_nothing_when_scale_is_current():
    assert price_scale_hint(TCS, date(2026, 12, 31)) is None
    assert price_scale_hint(None, date(2025, 12, 31)) is None


def test_hint_names_consolidation_correctly():
    hint = price_scale_hint([{"date": "2024-01-15", "ratio": 0.1}], date(2023, 12, 31))
    assert hint is not None and "консолидация 1:10" in hint


def test_seed_returns_copy_not_shared_state():
    first = seed_splits("T")
    assert first is not None
    first[0]["ratio"] = 999
    assert seed_splits("T")[0]["ratio"] == 10
    assert seed_splits("SBER") is None


def test_known_splits_are_well_formed():
    for ticker, entries in KNOWN_SPLITS.items():
        assert ticker.isupper()
        assert len(normalize_splits(entries)) == len(entries), f"{ticker}: запись не прошла разбор"
