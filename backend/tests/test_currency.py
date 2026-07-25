"""Конвертация денежных полей отчёта в рубли."""
from app.utils.currency_converter import convert_to_rub


def test_rub_is_identity():
    assert convert_to_rub(100.0, "RUB", None) == 100.0
    assert convert_to_rub(100.0, "RUB", 90.0) == 100.0


def test_usd_multiplies_by_rate():
    assert convert_to_rub(10.0, "USD", 90.0) == 900.0


def test_eur_multiplies_by_rate():
    """Курс хранится в отчёте для любой не-рублёвой валюты, не только USD."""
    assert convert_to_rub(10.0, "EUR", 100.0) == 1_000.0


def test_cny_multiplies_by_rate():
    assert convert_to_rub(100.0, "CNY", 12.5) == 1_250.0


def test_missing_value_stays_none():
    assert convert_to_rub(None, "USD", 90.0) is None


def test_foreign_currency_without_rate_returns_raw_value():
    """Без курса умножать не на что — возвращаем как есть (и выше по стеку
    сохранение такого отчёта должно было упасть на валидации)."""
    assert convert_to_rub(10.0, "USD", None) == 10.0
    assert convert_to_rub(10.0, "EUR", 0) == 10.0
