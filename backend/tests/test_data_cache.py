"""Кэш расчётов и ETag: без базы — версия данных подменяется."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import data_cache
from app.utils.http_cache import ETagMiddleware


def _fresh(monkeypatch):
    data_cache.clear()
    monkeypatch.setattr(data_cache, "_read_db_counter", lambda: 7)
    monkeypatch.setattr(data_cache, "_db_checked_at", 0.0)


def test_один_расчёт_на_версию_данных(monkeypatch):
    _fresh(monkeypatch)
    calls = []
    compute = lambda: calls.append(1) or len(calls)  # noqa: E731
    assert data_cache.cached("k", compute) == 1
    assert data_cache.cached("k", compute) == 1
    data_cache.bump()
    assert data_cache.cached("k", compute) == 2


def test_чужая_запись_видна_по_счётчику_postgres(monkeypatch):
    _fresh(monkeypatch)
    calls = []
    compute = lambda: calls.append(1) or len(calls)  # noqa: E731
    data_cache.cached("k", compute)
    monkeypatch.setattr(data_cache, "_read_db_counter", lambda: 8)
    monkeypatch.setattr(data_cache, "_db_checked_at", 0.0)
    assert data_cache.cached("k", compute) == 2


def test_ошибка_расчёта_не_кэшируется(monkeypatch):
    _fresh(monkeypatch)
    state = {"fail": True}

    def compute():
        if state["fail"]:
            raise ValueError("нет данных")
        return "ok"

    try:
        data_cache.cached("k", compute)
    except ValueError:
        pass
    state["fail"] = False
    assert data_cache.cached("k", compute) == "ok"


def test_ключ_обработчика_по_параметрам(monkeypatch):
    _fresh(monkeypatch)
    calls = []

    @data_cache.cached_route("t", "company_id", "window")
    def handler(company_id: int, window: int = 7, db=None):
        calls.append((company_id, window))
        return {"id": company_id, "window": window}

    handler(company_id=1, db="a")
    handler(company_id=1, window=7, db="b")  # то же самое — db в ключ не входит
    handler(1, 5)
    assert calls == [(1, 7), (1, 5)]


def test_записи_сессий_входа_версию_не_меняют():
    assert not data_cache._touches_data({"user_sessions", "users"})
    assert data_cache._touches_data({"financial_reports"})
    assert data_cache._touches_data({None})


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(ETagMiddleware)

    @app.get("/data")
    def data():
        return {"rows": list(range(100))}

    @app.get("/auth/me")
    def me():
        return {"user": None}

    return TestClient(app)


def test_etag_и_304_без_тела():
    client = _client()
    first = client.get("/data")
    etag = first.headers["etag"]
    assert etag.startswith('W/"')
    assert first.headers["cache-control"] == "private, no-cache"
    again = client.get("/data", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""
    other = client.get("/data", headers={"If-None-Match": 'W/"other"'})
    assert other.status_code == 200 and other.json()["rows"][-1] == 99


def test_вход_без_etag():
    assert "etag" not in _client().get("/auth/me").headers
