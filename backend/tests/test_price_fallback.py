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
