"""Аккаунты: регистрация, вход, сессии, ссылки из писем, защита от перебора.

Схема — серверные сессии в cookie (HttpOnly, SameSite=Strict), а не токены
в браузере: скрипт страницы сессию не видит, отозвать её можно с сервера.
Подробности и причины — в docs/SECURITY.md.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import ROLE_ADMIN, AuthToken, User, UserSession
from app.utils.passwords import dummy_hash, hash_password, password_problem, verify_password

logger = logging.getLogger("auth")

COOKIE_NAME = "ga_session"
# Отметку «был активен» пишем не чаще раза в пять минут.
TOUCH_EVERY = timedelta(minutes=5)
VERIFY_TTL = timedelta(hours=48)
RESET_TTL = timedelta(minutes=30)
EMAIL_TTL = timedelta(hours=24)
# Редакция текста согласия на обработку ПДн (страница /consent). Меняется
# текст — меняется и версия: видно, на что именно соглашался каждый.
CONSENT_VERSION = "2026-10-01"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class AuthError(Exception):
    """Ошибка, которую можно показать пользователю как есть."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    # SQLite (в тестах) теряет часовой пояс — считаем такое время UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def clean_name(name: str) -> str:
    # Управляющие символы и лишние пробелы — вон: имя показывается людям.
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return re.sub(r"\s+", " ", name).strip()[:64]


# ── Пользователи ─────────────────────────────────────────────────────────────

def register(db: Session, email: str, password: str, name: str, consent: bool = False) -> User:
    if not consent:
        raise AuthError("Без согласия на обработку данных аккаунт не создать")
    email = normalize_email(email)
    name = clean_name(name)
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("Похоже, в адресе почты ошибка")
    if len(name) < 2:
        raise AuthError("Имя — хотя бы два символа")
    problem = password_problem(password, email, name)
    if problem:
        raise AuthError(problem)
    if db.query(User).filter(User.email == email).first() is not None:
        raise AuthError("Эта почта уже зарегистрирована — войдите или восстановите пароль", 409)
    now = _now()
    user = User(email=email, display_name=name, password_hash=hash_password(password),
                password_changed_at=now, consent_at=now, consent_version=CONSENT_VERSION)
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info("регистрация: пользователь %s", user.id)
    return user


def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    """Пользователь, если почта и пароль верны. Время ответа одинаково для
    несуществующей почты и неверного пароля — иначе по нему видно, кто
    зарегистрирован."""
    user = db.query(User).filter(User.email == normalize_email(email)).first()
    if user is None:
        verify_password(password, dummy_hash())
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def set_password(db: Session, user: User, password: str, keep_session: Optional[str] = None) -> None:
    """Новый пароль. Все сессии, кроме текущей, закрываются."""
    problem = password_problem(password, user.email, user.display_name)
    if problem:
        raise AuthError(problem)
    user.password_hash = hash_password(password)
    user.password_changed_at = _now()
    query = db.query(UserSession).filter(UserSession.user_id == user.id)
    if keep_session:
        query = query.filter(UserSession.id_hash != _digest(keep_session))
    query.delete()
    db.commit()
    logger.info("пароль сменён: пользователь %s", user.id)


def delete_account(db: Session, user: User) -> None:
    if user.role == ROLE_ADMIN and db.query(User).filter(User.role == ROLE_ADMIN).count() <= 1:
        raise AuthError("Это единственный администратор — сначала назначьте другого")
    db.delete(user)
    db.commit()
    logger.info("аккаунт удалён: пользователь %s", user.id)


# ── Сессии ───────────────────────────────────────────────────────────────────

def create_session(db: Session, user: User, ip: Optional[str], user_agent: Optional[str]) -> tuple[str, datetime]:
    """Новая сессия — при каждом входе новый идентификатор."""
    raw = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=settings.SESSION_TTL_HOURS)
    db.add(UserSession(
        id_hash=_digest(raw), user_id=user.id, created_at=now, expires_at=expires,
        last_seen_at=now, ip=(ip or "")[:64], user_agent=(user_agent or "")[:256],
    ))
    user.last_login_at = now
    db.query(UserSession).filter(UserSession.expires_at < now).delete()
    db.commit()
    return raw, expires


def is_active(session, now: datetime) -> bool:
    if _aware(session.expires_at) <= now:
        return False
    return now - _aware(session.last_seen_at) <= timedelta(minutes=settings.SESSION_IDLE_MINUTES)


def current(db: Session, raw: Optional[str]) -> Optional[tuple[UserSession, User]]:
    """Действующая сессия и её пользователь — или None."""
    if not raw or len(raw) > 128:
        return None
    session = db.get(UserSession, _digest(raw))
    if session is None:
        return None
    now = _now()
    user = db.get(User, session.user_id)
    if user is None or not user.is_active or not is_active(session, now):
        db.delete(session)
        db.commit()
        return None
    if now - _aware(session.last_seen_at) >= TOUCH_EVERY:
        session.last_seen_at = now
        db.commit()
    return session, user


def end_session(db: Session, raw: Optional[str]) -> None:
    if not raw:
        return
    session = db.get(UserSession, _digest(raw))
    if session is not None:
        db.delete(session)
        db.commit()


def end_all_sessions(db: Session, user_id: Optional[int] = None, keep: Optional[str] = None) -> int:
    """Закрыть сессии пользователя (или всех), кроме `keep` — текущей."""
    query = db.query(UserSession)
    if user_id is not None:
        query = query.filter(UserSession.user_id == user_id)
    if keep:
        query = query.filter(UserSession.id_hash != _digest(keep))
    count = query.delete()
    db.commit()
    return count


def sessions_of(db: Session, user_id: int) -> list[UserSession]:
    return (db.query(UserSession).filter(UserSession.user_id == user_id)
            .order_by(UserSession.last_seen_at.desc()).all())


def purge_expired(db: Session) -> tuple[int, int]:
    """Удалить истёкшие сессии (по сроку и по простою) и отработавшие ссылки.
    Политика обещает: сведения о входе живут не дольше сессии."""
    now = _now()
    idle_since = now - timedelta(minutes=settings.SESSION_IDLE_MINUTES)
    sessions = db.query(UserSession).filter(
        (UserSession.expires_at <= now) | (UserSession.last_seen_at < idle_since)
    ).delete(synchronize_session=False)
    tokens = db.query(AuthToken).filter(
        (AuthToken.expires_at <= now) | AuthToken.used_at.isnot(None)
    ).delete(synchronize_session=False)
    db.commit()
    return sessions, tokens


# ── Ссылки из писем ──────────────────────────────────────────────────────────

def issue_token(db: Session, user: User, purpose: str, new_email: Optional[str] = None) -> str:
    """Одноразовая ссылка. Прежние неиспользованные того же назначения гаснут."""
    now = _now()
    db.query(AuthToken).filter(
        AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None),
    ).update({AuthToken.used_at: now})
    raw = secrets.token_urlsafe(32)
    ttl = {"verify": VERIFY_TTL, "reset": RESET_TTL, "email": EMAIL_TTL}[purpose]
    db.add(AuthToken(token_hash=_digest(raw), user_id=user.id, purpose=purpose, new_email=new_email,
                     created_at=now, expires_at=now + ttl))
    db.commit()
    return raw


def redeem_token(db: Session, raw: str, purpose: str) -> User:
    """Пользователь по ссылке; ссылка гаснет. Ошибка — одна на все случаи."""
    return _redeem(db, raw, purpose)[0]


def _redeem(db: Session, raw: str, purpose: str) -> tuple[User, AuthToken]:
    token = db.get(AuthToken, _digest(raw or ""))
    now = _now()
    if token is None or token.purpose != purpose or token.used_at is not None or _aware(token.expires_at) <= now:
        raise AuthError("Ссылка недействительна или устарела — запросите новую")
    user = db.get(User, token.user_id)
    if user is None or not user.is_active:
        raise AuthError("Ссылка недействительна или устарела — запросите новую")
    token.used_at = now
    db.commit()
    return user, token


def request_email_change(db: Session, user: User, new_email: str) -> str:
    """Ссылка для смены почты — уйдёт на новый адрес. Сама почта не
    меняется, пока по ссылке не перейдут: иначе опечатка заперла бы аккаунт."""
    new_email = normalize_email(new_email)
    if not EMAIL_RE.match(new_email) or len(new_email) > 254:
        raise AuthError("Похоже, в адресе почты ошибка")
    if new_email == user.email:
        raise AuthError("Это и так ваша почта")
    if db.query(User).filter(User.email == new_email).first() is not None:
        raise AuthError("Эта почта уже занята другим аккаунтом", 409)
    return issue_token(db, user, "email", new_email=new_email)


def confirm_email_change(db: Session, raw: str) -> tuple[User, str]:
    """Сменить почту по ссылке. Возвращает пользователя и прежний адрес."""
    user, token = _redeem(db, raw, "email")
    new_email = token.new_email or ""
    if db.query(User).filter(User.email == new_email, User.id != user.id).first() is not None:
        raise AuthError("Эта почта уже занята другим аккаунтом", 409)
    old = user.email
    user.email = new_email
    user.email_verified_at = _now()
    db.commit()
    logger.info("почта сменена: пользователь %s", user.id)
    return user, old


# ── Перебор ──────────────────────────────────────────────────────────────────

class Limiter:
    """Скользящее окно попыток по ключу, в памяти процесса.

    Хватает одного процесса uvicorn. Если их станет несколько, счётчики
    надо перенести в Redis — иначе лимит умножится на число процессов.
    """

    def __init__(self, max_hits: int, window_seconds: float):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) < self.max_hits:
                return 0
            return max(1, int(self.window - (now - q[0])))

    def hit(self, key: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._hits.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def _window() -> float:
    return settings.LOGIN_WINDOW_MINUTES * 60.0


# Неудачный вход — по адресу и по почте отдельно: адрес ловит перебор с
# одной машины, почта — распределённый перебор одного аккаунта.
login_by_ip = Limiter(settings.LOGIN_MAX_ATTEMPTS * 2, _window())
login_by_email = Limiter(settings.LOGIN_MAX_ATTEMPTS, _window())
# Регистрации и письма — по адресу в час: иначе нас используют как спамер.
register_by_ip = Limiter(5, 3600)
mail_by_ip = Limiter(5, 3600)
mail_by_email = Limiter(3, 3600)
