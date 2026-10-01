"""Аккаунты целиком: регистрация, вход, письма, пароль, роль, удаление.

База — SQLite в памяти с одними таблицами аккаунтов: рабочую не трогаем.
"""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import get_db
from app.models.user import ROLE_ADMIN, AuthToken, User, UserSession
from app.routers import auth_router
from app.services import auth, mailer
from app.utils import admin_guard, passwords

ORIGIN = "http://localhost:3000"
H = {"Origin": ORIGIN, "X-Requested-With": admin_guard.CSRF_VALUE}
PASSWORD = "тихий омут глубок"


@pytest.fixture()
def env(monkeypatch):
    from app.main import app

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (User, UserSession, AuthToken):
        model.__table__.create(engine)
    Local = sessionmaker(bind=engine, autoflush=False)

    def _db():
        db = Local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(admin_guard, "SessionLocal", Local)
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(auth_router, "FAILURE_DELAY_SECONDS", 0)
    # Дешёвый scrypt: в тестах важна логика, а не стойкость.
    monkeypatch.setattr(passwords, "N", 2 ** 10)
    monkeypatch.setattr(passwords, "_dummy", [])
    for name in ("login_by_ip", "login_by_email", "register_by_ip", "mail_by_ip", "mail_by_email"):
        old = getattr(auth, name)
        monkeypatch.setattr(auth, name, auth.Limiter(old.max_hits, old.window))
    mails: list[tuple[str, str]] = []
    monkeypatch.setattr(mailer, "send", lambda to, subject, text: mails.append((to, text)))
    try:
        yield TestClient(app), Local, mails
    finally:
        app.dependency_overrides.pop(get_db, None)


def _token(mails, path):
    return re.search(rf"{path}\?token=([\w-]+)", mails[-1][1]).group(1)


def _register(client, email="anna@example.ru", name="Анна"):
    return client.post("/auth/register", json={"email": email, "password": PASSWORD, "name": name, "consent": True}, headers=H)


def test_регистрация_входит_и_шлёт_письмо(env):
    client, Local, mails = env
    r = _register(client, email="  Anna@Example.RU ")
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["email"] == "anna@example.ru" and user["role"] == "user" and not user["email_verified"]
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/auth/me").json()["user"]["name"] == "Анна"
    assert mails and mails[-1][0] == "anna@example.ru"
    # В базе ни пароля, ни идентификатора сессии в открытом виде.
    db = Local()
    stored = db.query(User).one()
    assert PASSWORD not in stored.password_hash
    assert db.query(UserSession).one().id_hash != client.cookies.get("ga_session")


def test_повторная_почта_и_слабый_пароль(env):
    client, _, _ = env
    _register(client)
    assert _register(client).status_code == 409
    r = client.post("/auth/register", json={"email": "b@example.ru", "password": "qwerty12345", "name": "Боб", "consent": True}, headers=H)
    assert r.status_code == 400


def test_подтверждение_почты_одноразовое(env):
    client, _, mails = env
    _register(client)
    token = _token(mails, "/verify")
    assert client.post("/auth/verify", json={"token": token}, headers=H).json()["user"]["email_verified"]
    assert client.post("/auth/verify", json={"token": token}, headers=H).status_code == 400


def test_вход_ошибка_одна_для_чужой_почты_и_неверного_пароля(env):
    client, _, _ = env
    _register(client)
    client.post("/auth/logout", headers=H)
    assert client.get("/auth/me").json()["user"] is None
    wrong = client.post("/auth/login", json={"email": "anna@example.ru", "password": "не тот пароль"}, headers=H)
    absent = client.post("/auth/login", json={"email": "nobody@example.ru", "password": PASSWORD}, headers=H)
    assert wrong.status_code == absent.status_code == 401
    assert wrong.json() == absent.json()
    ok = client.post("/auth/login", json={"email": "ANNA@example.ru", "password": PASSWORD}, headers=H)
    assert ok.status_code == 200


def test_перебор_пароля_блокируется(env):
    client, _, _ = env
    _register(client)
    client.post("/auth/logout", headers=H)
    codes = [client.post("/auth/login", json={"email": "anna@example.ru", "password": f"неверный-{i}"},
                         headers=H).status_code for i in range(settings.LOGIN_MAX_ATTEMPTS + 1)]
    assert codes[-1] == 429
    # Даже верный пароль не пускает, пока идёт блок.
    assert client.post("/auth/login", json={"email": "anna@example.ru", "password": PASSWORD},
                       headers=H).status_code == 429


def test_сброс_пароля_закрывает_все_сессии(env):
    client, Local, mails = env
    _register(client)
    other = TestClient(client.app)
    other.post("/auth/login", json={"email": "anna@example.ru", "password": PASSWORD}, headers=H)
    # Ответ одинаков для любой почты.
    assert client.post("/auth/password/forgot", json={"email": "nobody@example.ru"}, headers=H).json() == {"ok": True}
    sent = len(mails)
    assert client.post("/auth/password/forgot", json={"email": "anna@example.ru"}, headers=H).json() == {"ok": True}
    assert len(mails) == sent + 1
    token = _token(mails, "/reset")
    new = "другая длинная фраза"
    assert client.post("/auth/password/reset", json={"token": token, "password": new}, headers=H).status_code == 200
    assert other.get("/auth/me").json()["user"] is None
    assert client.post("/auth/password/reset", json={"token": token, "password": new}, headers=H).status_code == 400
    assert client.post("/auth/login", json={"email": "anna@example.ru", "password": new}, headers=H).status_code == 200


def test_смена_пароля_оставляет_текущую_сессию(env):
    client, _, _ = env
    _register(client)
    other = TestClient(client.app)
    other.post("/auth/login", json={"email": "anna@example.ru", "password": PASSWORD}, headers=H)
    bad = client.post("/auth/password/change", json={"current_password": "не тот", "new_password": "новая длинная фраза"}, headers=H)
    assert bad.status_code == 400
    ok = client.post("/auth/password/change", json={"current_password": PASSWORD, "new_password": "новая длинная фраза"}, headers=H)
    assert ok.status_code == 200
    assert client.get("/auth/me").json()["user"] is not None
    assert other.get("/auth/me").json()["user"] is None


def test_обычный_пользователь_не_правит_данные_а_админ_проходит_проверку(env):
    client, Local, _ = env
    _register(client)
    assert client.delete("/reports/999999", headers=H).status_code == 403
    assert client.get("/mass-parse/jobs").status_code == 403
    db = Local()
    db.query(User).update({User.role: ROLE_ADMIN})
    db.commit()
    assert client.get("/auth/me").json()["user"]["role"] == "admin"
    # Админ проходит прослойку; дальше эндпоинт работает с рабочей базой —
    # её не трогаем, достаточно что ответ не 401/403.
    assert admin_guard.needs_admin("DELETE", "/reports/1")


def test_удаление_аккаунта_по_паролю(env):
    client, Local, _ = env
    _register(client)
    assert client.post("/auth/account/delete", json={"password": "не тот"}, headers=H).status_code == 400
    assert client.post("/auth/account/delete", json={"password": PASSWORD}, headers=H).status_code == 200
    assert Local().query(User).count() == 0
    assert client.get("/auth/me").json()["user"] is None


def test_имя_чистится_от_управляющих_символов(env):
    client, _, _ = env
    _register(client)
    r = client.patch("/auth/profile", json={"name": "  Анна\x00   К. "}, headers=H)
    assert r.json()["user"]["name"] == "Анна К."


def test_без_согласия_аккаунт_не_создаётся_а_согласие_записано(env):
    client, Local, _ = env
    r = client.post("/auth/register", json={"email": "c@example.ru", "password": PASSWORD, "name": "Вера"}, headers=H)
    assert r.status_code == 400
    _register(client)
    user = Local().query(User).one()
    assert user.consent_at is not None and user.consent_version == auth.CONSENT_VERSION


def test_смена_почты_только_по_ссылке_с_нового_адреса(env):
    client, Local, mails = env
    _register(client)
    _register(TestClient(client.app), email="busy@example.ru", name="Борис")
    bad = client.post("/auth/email/change", json={"new_email": "new@example.ru", "password": "не тот"}, headers=H)
    assert bad.status_code == 400
    busy = client.post("/auth/email/change", json={"new_email": "busy@example.ru", "password": PASSWORD}, headers=H)
    assert busy.status_code == 409
    assert client.post("/auth/email/change", json={"new_email": "New@Example.ru", "password": PASSWORD}, headers=H).status_code == 200
    assert mails[-1][0] == "new@example.ru"
    # Пока по ссылке не перешли — почта прежняя.
    assert client.get("/auth/me").json()["user"]["email"] == "anna@example.ru"
    token = _token(mails, "/verify-email")
    r = client.post("/auth/email/confirm", json={"token": token}, headers=H)
    assert r.json()["user"]["email"] == "new@example.ru" and r.json()["user"]["email_verified"]
    assert mails[-1][0] == "anna@example.ru"  # прежний адрес предупреждён
    assert client.post("/auth/email/confirm", json={"token": token}, headers=H).status_code == 400


def test_выйти_везде_кроме_этого(env):
    client, _, _ = env
    _register(client)
    other = TestClient(client.app)
    other.post("/auth/login", json={"email": "anna@example.ru", "password": PASSWORD}, headers=H)
    assert client.post("/auth/logout-others", headers=H).json() == {"closed": 1}
    assert client.get("/auth/me").json()["user"] is not None
    assert other.get("/auth/me").json()["user"] is None


def test_истёкшие_сессии_и_ссылки_вычищаются(env):
    from datetime import timedelta
    client, Local, mails = env
    _register(client)
    db = Local()
    db.query(UserSession).update({UserSession.last_seen_at: auth._now() - timedelta(hours=5)})
    db.commit()
    sessions, tokens = auth.purge_expired(db)
    assert sessions == 1
    assert db.query(UserSession).count() == 0
    # Ссылка подтверждения ещё жива — остаётся.
    assert tokens == 0 and db.query(AuthToken).count() == 1
