"""Общие фикстуры для тестов расчётов.

Тесты сознательно НЕ трогают базу: расчётный слой принимает объект отчёта и
читает его атрибуты, поэтому вместо ORM-модели достаточно простой заглушки.
Так тесты остаются быстрыми и переживают миграции схемы.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

# Значения по умолчанию — условная промышленная компания, отчёт в рублях.
# Цифры круглые, чтобы ожидаемый результат считался в уме и был виден глазами.
_DEFAULTS: dict[str, Any] = {
    "report_type": "general",
    "currency": "RUB",
    "exchange_rate": None,
    # Цена и акции: 100 ₽ × 1 млрд шт = 100 млрд ₽ капитализации
    "price_per_share": 100.0,
    "shares_outstanding": 1_000_000_000,
    "shares_issued": None,
    "shares_weighted_avg": None,
    "treasury_shares": None,
    # P&L, млн ₽
    "revenue": 50_000.0,
    "net_income": 10_000.0,
    "net_income_reported": 10_000.0,
    # Баланс, млн ₽
    "equity": 50_000.0,
    "goodwill": None,
    "total_assets": 100_000.0,
    "total_liabilities": 25_000.0,
    "current_assets": 30_000.0,
    "current_liabilities": 15_000.0,
    "cash_and_equivalents": 5_000.0,
    "debt": 20_000.0,
    # ОДДС, млн ₽ (оттоки — положительными числами)
    "operating_cash_flow": 15_000.0,
    "capex": 5_000.0,
    "lease_principal": None,
    "lease_interest": None,
    "interest_paid": None,
    "debt_principal": None,
    "depreciation_amortization": 4_000.0,
    # Дивиденды, ₽ на акцию
    "dividends_paid": True,
    "dividends_per_share": 6.0,
    "special_dividends_per_share": None,
    "special_dividends_note": None,
    # Банковские поля
    "operating_expenses": None,
    "net_interest_income": None,
    "fee_commission_income": None,
    "provisions": None,
}


def build_report(**overrides: Any) -> SimpleNamespace:
    """Отчёт-заглушка: значения по умолчанию плюс переданные переопределения."""
    unknown = set(overrides) - set(_DEFAULTS)
    if unknown:
        raise AssertionError(
            f"В заглушке отчёта нет полей: {sorted(unknown)}. "
            f"Добавь их в _DEFAULTS, иначе тест проверяет опечатку, а не расчёт."
        )
    data = {**_DEFAULTS, **overrides}
    return SimpleNamespace(**data)


@pytest.fixture
def report_factory():
    """Фабрика отчётов для тестов, которым нужно несколько разных вариантов."""
    return build_report


@pytest.fixture
def report() -> SimpleNamespace:
    """Базовый отчёт промышленной компании в рублях."""
    return build_report()
