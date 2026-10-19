"""Резерв для T-Invest: предохранитель, цены Мосбиржи, логотипы."""
from datetime import datetime, timedelta, timezone

from app.utils import moex_client
from app.utils.source_health import SourceBreaker
from app.services.companies.logo_cache import _sized


def test_breaker_pauses_after_failure_and_doubles():
    now = [datetime(2026, 10, 12, tzinfo=timezone.utc)]
    b = SourceBreaker("x", "x", clock=lambda: now[0])
    assert b.available()
    b.failure("down")
    assert not b.available()
    now[0] += timedelta(minutes=1)
    assert b.available()
    b.failure("down again")
    now[0] += timedelta(minutes=1, seconds=30)
    assert not b.available()          # вторая пауза — две минуты
    b.success()
    assert b.available() and b.status()["state"] == "ok"


def test_moex_prices_prefer_main_board_and_skip_otc(monkeypatch):
    payload = {"marketdata": {
        "columns": ["SECID", "BOARDID", "LAST", "LCURRENTPRICE", "UPDATETIME", "SYSTIME"],
        "data": [
            ["SBER", "SPEQ", 999.0, None, "18:00:00", "2026-10-12 18:01:00"],
            ["SBER", "SMAL", 280.0, None, "18:00:00", "2026-10-12 18:01:00"],
            ["SBER", "TQBR", 285.39, 285.3, "18:00:00", "2026-10-12 18:01:00"],
            ["GAZP", "TQBR", None, 101.5, "18:10:00", "2026-10-12 18:11:00"],
            ["XXXX", "SPEQ", 1.0, None, "18:00:00", "2026-10-12 18:01:00"],
        ]}}

    class Resp:
        def raise_for_status(self): pass
        def json(self): return payload

    monkeypatch.setattr(moex_client, "_moex_get", lambda *a, **k: Resp())
    got = moex_client.get_last_prices(["SBER", "GAZP", "XXXX"])
    assert got["SBER"][0] == 285.39
    assert got["GAZP"][0] == 101.5                       # вне торгов — LCURRENTPRICE
    assert "XXXX" not in got                             # внебиржевую цену не берём
    assert got["SBER"][1] == datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)  # МСК → UTC


def test_logo_url_gets_size_suffix():
    urls = _sized("https://invest-brands.cdn-tinkoff.ru/sber3.png")
    assert urls[0] == "https://invest-brands.cdn-tinkoff.ru/sber3x160.png"
    assert _sized("https://invest-brands.cdn-tinkoff.ru/RU0009029540x160.png") == [
        "https://invest-brands.cdn-tinkoff.ru/RU0009029540x160.png"]


def test_moex_quote_after_midnight_is_yesterday():
    # Ночью или в субботу котировка пятничная, хотя системная дата новая.
    got = moex_client._quote_time("2026-10-17 03:00:00", "23:49:00")
    assert got == datetime(2026, 10, 16, 20, 49, tzinfo=timezone.utc)


def test_tinvest_trade_time_parsed_with_nanoseconds():
    from app.services.market.tinvest_price_service import _parse_time

    assert _parse_time("2026-10-13T12:34:56.123456789Z") == datetime(
        2026, 10, 13, 12, 34, 56, 123456, tzinfo=timezone.utc)
    assert _parse_time(None) is None


class _Company:
    id = 1
    current_price = None
    price_source = None
    price_updated_at = None
    price_quoted_at = None


def test_unchanged_price_is_not_written(monkeypatch):
    from app.services.market import tinvest_price_service as svc

    rows = []
    monkeypatch.setattr(svc, "_upsert_stock_price",
                        lambda db, company_id, price_date, price, source: rows.append(price_date))
    company = _Company()
    morning = datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)
    assert svc._apply_price(None, company, 100.0, "tinvest", morning, morning)
    later = morning + timedelta(minutes=5)
    assert not svc._apply_price(None, company, 100.0, "tinvest", later, later)
    assert company.price_quoted_at == morning            # время, когда цена стала такой
    assert svc._apply_price(None, company, 101.0, "tinvest", later, later)
    assert len(rows) == 2


def test_daily_row_dated_by_moscow_quote_day(monkeypatch):
    from app.services.market import tinvest_price_service as svc

    rows = []
    monkeypatch.setattr(svc, "_upsert_stock_price",
                        lambda db, company_id, price_date, price, source: rows.append(price_date))
    friday_close = datetime(2026, 10, 16, 20, 49, tzinfo=timezone.utc)   # 23:49 МСК
    saturday = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
    svc._apply_price(None, _Company(), 100.0, "moex", friday_close, saturday)
    assert rows == [friday_close.date()]
    late_utc = datetime(2026, 10, 13, 22, 30, tzinfo=timezone.utc)       # 01:30 МСК 14-го
    svc._apply_price(None, _Company(), 100.0, "tinvest", late_utc, late_utc)
    assert str(rows[-1]) == "2026-10-14"
