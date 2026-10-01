"""События на графике: разбор ответа T-Invest и подписи."""

from datetime import date

from app.routers.prices_router import _money_ru
from app.services.market.corporate_events_service import _day, _money


def test_quotation_t_invest_в_число():
    assert _money({"units": "278", "nano": 0}) == 278.0
    assert _money({"units": "11", "nano": 900000000}) == 11.9
    assert _money(None) is None


def test_дата_из_метки_времени():
    assert _day("2026-05-04T00:00:00Z") == date(2026, 5, 4)
    assert _day("") is None
    assert _day("не дата") is None


def test_подпись_суммы_по_русски():
    assert _money_ru(278.0, "RUB") == "278 ₽"
    assert _money_ru(11.9, "RUB") == "11,90 ₽"
    assert _money_ru(1234.5, "USD") == "1 234,50 USD"
