"""Доступ: гость читает, администратор пишет; CSRF; вход."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.routers import auth_router
from app.services.auth import Limiter, is_active
from app.utils.admin_guard import CSRF_VALUE, needs_admin, origin_allowed
from app.utils.passwords import hash_password, password_problem, verify_password

ORIGIN = "http://localhost:3000"
GOOD = {"Origin": ORIGIN, "X-Requested-With": CSRF_VALUE}


# ── Что закрыто ──

def test_запись_закрыта_чтение_открыто():
    assert needs_admin("POST", "/reports/")
    assert needs_admin("DELETE", "/reports/5")
    assert needs_admin("PATCH", "/companies/1/description")
    assert not needs_admin("GET", "/valuation/company/21/summary")
    assert not needs_admin("GET", "/disclosure/calendar")
    assert not needs_admin("GET", "/market/overview")


def test_служебное_закрыто_и_на_чтение():
    for path in ("/mass-parse/jobs", "/admin/x", "/bonds/", "/securities/",
                 "/market/price/moex", "/market/fx/rate", "/disclosure/coverage", "/companies/sync/status"):
        assert needs_admin("GET", path), path


def test_аккаунты_не_требуют_роли():
    for path in ("/auth/login", "/auth/logout", "/auth/register", "/auth/password/forgot", "/auth/profile"):
        assert not needs_admin("POST", path), path
    # Но похожий путь вне /auth — уже служебный.
    assert needs_admin("POST", "/authx")


# ── Пароль ──

def test_пароль_хранится_хэшем_и_проверяется():
    stored = hash_password("correct horse battery")
    assert "correct" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("correct horse batterY", stored)
    # Соль своя: два хэша одного пароля различаются.
    assert stored != hash_password("correct horse battery")


def test_короткий_пароль_не_принимается():
    with pytest.raises(ValueError):
        hash_password("short")


def test_битый_хэш_не_пускает():
    assert not verify_password("anything", "garbage")


# ── Сессия и перебор ──

def test_сессия_истекает_по_сроку_и_по_простою(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_IDLE_MINUTES", 120)
    now = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    live = SimpleNamespace(expires_at=now + timedelta(hours=1), last_seen_at=now - timedelta(minutes=10))
    assert is_active(live, now)
    expired = SimpleNamespace(expires_at=now - timedelta(seconds=1), last_seen_at=now)
    assert not is_active(expired, now)
    idle = SimpleNamespace(expires_at=now + timedelta(hours=5), last_seen_at=now - timedelta(minutes=121))
    assert not is_active(idle, now)


def test_после_пяти_неудач_вход_закрыт_на_окно():
    lim = Limiter(5, 15 * 60)
    for i in range(4):
        lim.hit("1.2.3.4", now=100.0 + i)
    assert lim.retry_after("1.2.3.4", now=105.0) == 0
    lim.hit("1.2.3.4", now=105.0)
    assert lim.retry_after("1.2.3.4", now=106.0) > 0
    # Другой ключ не задет, а окно проходит.
    assert lim.retry_after("5.6.7.8", now=106.0) == 0
    assert lim.retry_after("1.2.3.4", now=100.0 + 15 * 60 + 10) == 0


def test_правила_пароля():
    assert password_problem("short") is not None
    assert password_problem("qwerty12345") is not None          # из утечек
    assert password_problem("aaaaabbbbbb") is not None          # мало разных символов
    assert password_problem("ivanov-secret-42", email="ivanov@mail.ru") is not None
    assert password_problem("тихий омут глубок") is None        # длинная фраза годится
    assert password_problem("x" * 129) is not None


# ── CSRF ──

def test_источник_запроса_сверяется_со_списком(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "http://localhost:3000")
    assert origin_allowed("http://localhost:3000", None)
    assert not origin_allowed("https://evil.example", None)
    assert origin_allowed(None, "http://localhost:3000/company/1")
    assert not origin_allowed(None, None)


# ── Через приложение ──

@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(auth_router, "FAILURE_DELAY_SECONDS", 0)
    return TestClient(app)


def test_запись_без_входа_даёт_401(client):
    response = client.delete("/reports/1", headers=GOOD)
    assert response.status_code == 401


def test_запись_с_чужого_сайта_отклоняется_раньше_проверки_входа(client):
    assert client.delete("/reports/1", headers={"Origin": "https://evil.example",
                                                 "X-Requested-With": CSRF_VALUE}).status_code == 403
    assert client.delete("/reports/1", headers={"Origin": ORIGIN}).status_code == 403


def test_вход_без_csrf_заголовков_отклоняется(client):
    assert client.post("/auth/login", json={"email": "a@b.ru", "password": "x"}).status_code == 403
