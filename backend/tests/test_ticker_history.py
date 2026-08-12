"""Подстановка прежнего тикера по дате."""

from datetime import date

import pytest

from app.services.ticker_history import (
    KNOWN_TICKER_CHANGES,
    describe_chain,
    normalize_former_tickers,
    resolve_ticker,
    seed_former_tickers,
    ticker_chain,
)

YANDEX = [{"ticker": "YNDX", "until": "2024-07-07"}]
# ОГК-4 → Э.ОН Россия → Юнипро: цепочка из трёх символов у одной компании
UNIPRO = [
    {"ticker": "EONR", "until": "2016-06-30"},
    {"ticker": "OGKD", "until": "2007-04-24"},
]


def test_date_before_rename_uses_old_ticker():
    assert resolve_ticker("YDEX", YANDEX, date(2022, 12, 30)) == "YNDX"


def test_date_after_rename_uses_current_ticker():
    assert resolve_ticker("YDEX", YANDEX, date(2024, 12, 30)) == "YDEX"


def test_rename_day_itself_belongs_to_old_ticker():
    """Граница включительная: 7 июля — последний день YNDX."""
    assert resolve_ticker("YDEX", YANDEX, date(2024, 7, 7)) == "YNDX"
    assert resolve_ticker("YDEX", YANDEX, date(2024, 7, 8)) == "YDEX"


@pytest.mark.parametrize(
    "year, expected",
    [(2006, "OGKD"), (2013, "EONR"), (2020, "UPRO")],
)
def test_chain_of_three_picks_the_right_link(year, expected):
    assert resolve_ticker("UPRO", UNIPRO, date(year, 12, 31)) == expected


def test_no_history_returns_current_ticker():
    assert resolve_ticker("SBER", None, date(2015, 12, 31)) == "SBER"
    assert resolve_ticker("SBER", [], date(2015, 12, 31)) == "SBER"


def test_unknown_date_returns_current_ticker():
    assert resolve_ticker("YDEX", YANDEX, None) == "YDEX"


def test_order_in_storage_does_not_matter():
    """Записи нормализуются по дате, порядок ввода значения не имеет."""
    shuffled = list(reversed(UNIPRO))
    assert resolve_ticker("UPRO", shuffled, date(2013, 12, 31)) == "EONR"


def test_broken_entries_are_dropped_not_raised():
    """Опечатка в одной строке не должна ломать поиск цены целиком."""
    messy = [
        {"ticker": "YNDX", "until": "2024-07-07"},
        {"ticker": "", "until": "2020-01-01"},
        {"ticker": "XXXX", "until": "не дата"},
        {"until": "2019-01-01"},
        "мусор",
        None,
    ]
    assert normalize_former_tickers(messy) == [{"ticker": "YNDX", "until": "2024-07-07"}]
    assert resolve_ticker("YDEX", messy, date(2022, 1, 1)) == "YNDX"


def test_ticker_is_uppercased():
    assert resolve_ticker("YDEX", [{"ticker": "yndx", "until": "2024-07-07"}],
                          date(2022, 1, 1)) == "YNDX"


def test_normalize_accepts_date_objects():
    """Форма может прислать дату объектом, а не строкой."""
    assert normalize_former_tickers([{"ticker": "YNDX", "until": date(2024, 7, 7)}]) == [
        {"ticker": "YNDX", "until": "2024-07-07"}
    ]


def test_chain_lists_current_first_then_older():
    assert ticker_chain("UPRO", UNIPRO) == ["UPRO", "EONR", "OGKD"]


def test_describe_chain_is_readable():
    assert describe_chain("YDEX", YANDEX) == "YNDX (по 2024-07-07) → YDEX"
    assert describe_chain("SBER", None) == "SBER"


def test_seed_returns_copy_not_shared_state():
    """Скрипт заполнения кладёт результат в ORM — общий объект был бы миной."""
    first = seed_former_tickers("YDEX")
    assert first is not None
    first[0]["ticker"] = "ИСПОРЧЕНО"
    assert seed_former_tickers("YDEX")[0]["ticker"] == "YNDX"
    assert seed_former_tickers("SBER") is None


def test_known_changes_are_well_formed():
    for current, entries in KNOWN_TICKER_CHANGES.items():
        assert current.isupper()
        normalized = normalize_former_tickers(entries)
        assert len(normalized) == len(entries), f"{current}: запись не прошла разбор"
        for entry in normalized:
            assert entry["ticker"] != current, f"{current}: сам себе прежний тикер"
