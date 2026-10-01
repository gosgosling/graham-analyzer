"""Какие инструменты попадают в базу из T-Invest.

Список Shares отдаёт все линии эмитента разом, включая зарубежные. Страна
риска у них та же российская, и прежний фильтр их пропускал — в базе заводился
двойник, наполнить который нечем: котировки берутся у Мосбиржи, а там этих
бумаг нет. Удаление не помогало, следующая синхронизация заводила их заново.
"""

from app.utils.tinkoff_client import instrument_is_wanted


def share(**values) -> dict:
    base = {
        "ticker": "TEST",
        "isin": "RU0001234567",
        "currency": "rub",
        "country_of_risk": "RU",
        "exchange": "MOEX",
    }
    base.update(values)
    return base


def test_an_ordinary_moex_share_is_taken():
    assert instrument_is_wanted(share()) is True


def test_a_foreign_line_of_a_russian_issuer_is_skipped():
    """CIAN@US: страна риска Россия, но бумага долларовая и на Мосбирже её
    нет. Рядом уже стоит CNRU с той же отчётностью."""
    assert instrument_is_wanted(share(
        ticker="CIAN@US", isin="US83418T1088", currency="usd", exchange="spb",
    )) is False


def test_the_rouble_line_of_the_same_issuer_survives():
    """У VEON две записи: долларовая и рублёвая. Нужна вторая."""
    assert instrument_is_wanted(share(ticker="VEON", currency="usd")) is False
    assert instrument_is_wanted(share(ticker="VEON-RX", currency="rub")) is True


def test_a_foreign_company_is_skipped_even_on_a_russian_venue():
    """Freedom Holding зарегистрирован в США и отчитывается не по нашим
    правилам — анализировать его этим инструментом нечем."""
    assert instrument_is_wanted(share(
        ticker="FRHC", isin="US3563901046", currency="usd", country_of_risk="US",
    )) is False


def test_a_missing_currency_is_not_a_reason_to_drop_a_share():
    """Выше по коду пустая валюта уже заменяется на рубли; молча выбрасывать
    бумагу из-за незаполненного поля было бы хуже, чем взять лишнюю."""
    assert instrument_is_wanted(share(currency=None)) is True


def test_a_rouble_share_outside_moex_is_still_taken():
    """Правило про рынок не менялось: рублёвая бумага российского эмитента
    остаётся нужной, даже если площадка в ответе названа иначе."""
    assert instrument_is_wanted(share(exchange="unknown")) is True


def test_the_six_entries_that_were_deleted_do_not_come_back():
    """Поимённо — те записи, что однажды уже завелись и были вычищены.

    Страна риска и площадка заданы самыми благоприятными: даже если T-Invest
    назовёт бумагу российской и мосбиржевой, долларовая линия в базу не
    попадёт. Иначе чистка обнулится при первой же синхронизации.
    """
    junk = {
        "CIAN@US": "US83418T1088",   # рядом стоит CNRU
        "FIVE@GS": "US98387E2054",   # рядом стоит X5
        "VEON": "US91822M5022",      # рядом стоит VEON-RX
        "GLTR@GS": "US37949E2046",   # ушёл с Мосбиржи в 2024-м
        "FRHC": "US3563901046",      # американская регистрация
        "YNDX@US": "NL0009805522",   # это Nebius, а не Яндекс
    }
    for ticker, isin in junk.items():
        assert instrument_is_wanted(share(
            ticker=ticker, isin=isin, currency="usd",
            country_of_risk="RU", exchange="MOEX",
        )) is False, ticker
