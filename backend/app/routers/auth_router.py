"""Аккаунты: регистрация, вход и выход, почта, пароль, сессии."""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import auth, mailer
from app.services.auth import COOKIE_NAME, AuthError
from app.utils.admin_guard import client_ip

logger = logging.getLogger("auth")
router = APIRouter(prefix="/auth", tags=["auth"])

# Неудачный вход отвечает не сразу: перебор медленнее.
FAILURE_DELAY_SECONDS = 1.0


class RegisterIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)
    name: str = Field(..., max_length=64)
    consent: bool = False


class LoginIn(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class EmailIn(BaseModel):
    email: str = Field(..., max_length=254)


class TokenIn(BaseModel):
    token: str = Field(..., max_length=128)


class ResetIn(BaseModel):
    token: str = Field(..., max_length=128)
    password: str = Field(..., max_length=256)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., max_length=256)
    new_password: str = Field(..., max_length=256)


class EmailChangeIn(BaseModel):
    new_email: str = Field(..., max_length=254)
    password: str = Field(..., max_length=256)


class ProfileIn(BaseModel):
    name: str = Field(..., max_length=64)


class DeleteIn(BaseModel):
    password: str = Field(..., max_length=256)


# ── помощники ──

def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.display_name,
        "role": user.role,
        "email_verified": user.email_verified_at is not None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "password_changed_at": user.password_changed_at.isoformat() if user.password_changed_at else None,
        "consent_at": user.consent_at.isoformat() if user.consent_at else None,
    }


def _error(err: AuthError) -> JSONResponse:
    return JSONResponse(status_code=err.status, content={"detail": err.message})


def _too_many(wait: int) -> JSONResponse:
    minutes = max(1, (wait + 59) // 60)
    return JSONResponse(status_code=429, content={"detail": f"Слишком много попыток. Попробуйте через {minutes} мин."},
                        headers={"Retry-After": str(wait)})


def _login_response(db: Session, user: User, request: Request) -> JSONResponse:
    raw, expires = auth.create_session(db, user, client_ip(request), request.headers.get("user-agent"))
    response = JSONResponse({"user": _user_out(user), "expires_at": expires.isoformat()})
    response.set_cookie(COOKIE_NAME, raw, max_age=settings.SESSION_TTL_HOURS * 3600, path="/",
                        httponly=True, secure=settings.COOKIE_SECURE, samesite="strict")
    return response


def _require(db: Session, request: Request):
    found = auth.current(db, request.cookies.get(COOKIE_NAME))
    if found is None:
        raise AuthError("Нужно войти", 401)
    return found


def _link(path: str, token: str) -> str:
    return f"{settings.PUBLIC_SITE_URL.rstrip('/')}{path}?token={token}"


def _send_verify(db: Session, user: User) -> None:
    token = auth.issue_token(db, user, "verify")
    mailer.send(user.email, "Подтвердите почту — Graham Analyzer", (
        f"Здравствуйте, {user.display_name}!\n\n"
        f"Чтобы подтвердить адрес, откройте ссылку (действует 48 часов):\n{_link('/verify', token)}\n\n"
        "Если вы не регистрировались на Graham Analyzer, просто удалите письмо."
    ))


# ── регистрация и вход ──

@router.post("/register")
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    wait = auth.register_by_ip.retry_after(ip)
    if wait:
        return _too_many(wait)
    auth.register_by_ip.hit(ip)
    try:
        user = auth.register(db, payload.email, payload.password, payload.name, payload.consent)
    except AuthError as err:
        return _error(err)
    _send_verify(db, user)
    return _login_response(db, user, request)


@router.post("/login")
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    email = auth.normalize_email(payload.email)
    wait = max(auth.login_by_ip.retry_after(ip), auth.login_by_email.retry_after(email))
    if wait:
        logger.warning("вход: блок для %s / %s ещё %d с", ip, email[:3] + "…", wait)
        return _too_many(wait)
    user = auth.authenticate(db, email, payload.password)
    if user is None:
        auth.login_by_ip.hit(ip)
        auth.login_by_email.hit(email)
        time.sleep(FAILURE_DELAY_SECONDS)
        logger.warning("вход: неудача с %s", ip)
        return JSONResponse(status_code=401, content={"detail": "Неверная почта или пароль"})
    auth.login_by_ip.reset(ip)
    auth.login_by_email.reset(email)
    logger.info("вход: пользователь %s с %s", user.id, ip)
    return _login_response(db, user, request)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    auth.end_session(db, request.cookies.get(COOKIE_NAME))
    response = JSONResponse({"user": None})
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict", secure=settings.COOKIE_SECURE, httponly=True)
    return response


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)) -> dict:
    found = auth.current(db, request.cookies.get(COOKIE_NAME))
    if found is None:
        return {"user": None, "expires_at": None, "mail_configured": mailer.configured()}
    session, user = found
    return {"user": _user_out(user), "expires_at": session.expires_at.isoformat(),
            "mail_configured": mailer.configured()}


# ── почта ──

@router.post("/verify")
def verify(payload: TokenIn, db: Session = Depends(get_db)):
    try:
        user = auth.redeem_token(db, payload.token, "verify")
    except AuthError as err:
        return _error(err)
    if user.email_verified_at is None:
        user.email_verified_at = auth._now()
        db.commit()
    return {"user": _user_out(user)}


@router.post("/verify/resend")
def resend_verify(request: Request, db: Session = Depends(get_db)):
    try:
        _, user = _require(db, request)
    except AuthError as err:
        return _error(err)
    wait = auth.mail_by_email.retry_after(user.email)
    if wait:
        return _too_many(wait)
    auth.mail_by_email.hit(user.email)
    if user.email_verified_at is None:
        _send_verify(db, user)
    return {"ok": True}


@router.post("/email/change")
def change_email(payload: EmailChangeIn, request: Request, db: Session = Depends(get_db)):
    """Ссылка на новый адрес; почта сменится, когда по ней перейдут."""
    try:
        _, user = _require(db, request)
        wait = auth.mail_by_email.retry_after(user.email)
        if wait:
            return _too_many(wait)
        if not auth.authenticate(db, user.email, payload.password):
            time.sleep(FAILURE_DELAY_SECONDS)
            raise AuthError("Пароль неверен", 400)
        token = auth.request_email_change(db, user, payload.new_email)
    except AuthError as err:
        return _error(err)
    auth.mail_by_email.hit(user.email)
    new_email = auth.normalize_email(payload.new_email)
    mailer.send(new_email, "Подтвердите новую почту — Graham Analyzer", (
        f"Здравствуйте, {user.display_name}!\n\n"
        f"Чтобы сделать этот адрес почтой аккаунта, откройте ссылку (действует 24 часа):\n{_link('/verify-email', token)}\n\n"
        "Если вы ничего не меняли, просто удалите письмо."
    ))
    return {"ok": True}


@router.post("/email/confirm")
def confirm_email(payload: TokenIn, db: Session = Depends(get_db)):
    try:
        user, old = auth.confirm_email_change(db, payload.token)
    except AuthError as err:
        return _error(err)
    # Прежний адрес узнаёт о смене: если это не владелец — он заметит.
    mailer.send(old, "Почта аккаунта изменена — Graham Analyzer", (
        f"Здравствуйте, {user.display_name}!\n\n"
        "Почта вашего аккаунта на Graham Analyzer только что изменена. Если это сделали не вы, "
        f"восстановите доступ: {settings.PUBLIC_SITE_URL.rstrip('/')}/forgot — и напишите нам."
    ))
    return {"user": _user_out(user)}


# ── пароль ──

@router.post("/password/forgot")
def forgot(payload: EmailIn, request: Request, db: Session = Depends(get_db)):
    """Ответ одинаковый, есть такая почта или нет: иначе по нему видно,
    кто зарегистрирован."""
    ip = client_ip(request)
    email = auth.normalize_email(payload.email)
    wait = max(auth.mail_by_ip.retry_after(ip), auth.mail_by_email.retry_after(email))
    if wait:
        return _too_many(wait)
    auth.mail_by_ip.hit(ip)
    auth.mail_by_email.hit(email)
    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()
    if user is not None:
        token = auth.issue_token(db, user, "reset")
        mailer.send(user.email, "Сброс пароля — Graham Analyzer", (
            f"Здравствуйте, {user.display_name}!\n\n"
            f"Чтобы задать новый пароль, откройте ссылку (действует 30 минут):\n{_link('/reset', token)}\n\n"
            "Если вы не просили сбросить пароль, ничего не делайте — он не изменится."
        ))
    return {"ok": True}


@router.post("/password/reset")
def reset(payload: ResetIn, db: Session = Depends(get_db)):
    try:
        user = auth.redeem_token(db, payload.token, "reset")
        auth.set_password(db, user, payload.password)
    except AuthError as err:
        return _error(err)
    # Ссылка пришла на почту — значит, почта настоящая.
    if user.email_verified_at is None:
        user.email_verified_at = auth._now()
        db.commit()
    return {"ok": True}


@router.post("/password/change")
def change_password(payload: ChangePasswordIn, request: Request, db: Session = Depends(get_db)):
    try:
        _, user = _require(db, request)
        if not auth.authenticate(db, user.email, payload.current_password):
            time.sleep(FAILURE_DELAY_SECONDS)
            raise AuthError("Текущий пароль неверен", 400)
        auth.set_password(db, user, payload.new_password, keep_session=request.cookies.get(COOKIE_NAME))
    except AuthError as err:
        return _error(err)
    return {"ok": True}


# ── профиль и сессии ──

@router.patch("/profile")
def update_profile(payload: ProfileIn, request: Request, db: Session = Depends(get_db)):
    try:
        _, user = _require(db, request)
    except AuthError as err:
        return _error(err)
    name = auth.clean_name(payload.name)
    if len(name) < 2:
        return _error(AuthError("Имя — хотя бы два символа"))
    user.display_name = name
    db.commit()
    return {"user": _user_out(user)}


@router.get("/sessions")
def list_sessions(request: Request, db: Session = Depends(get_db)):
    try:
        session, user = _require(db, request)
    except AuthError as err:
        return _error(err)
    return [{
        "current": s.id_hash == session.id_hash,
        "created_at": s.created_at.isoformat(),
        "last_seen_at": s.last_seen_at.isoformat(),
        "ip": s.ip,
        "user_agent": s.user_agent,
    } for s in auth.sessions_of(db, user.id)]


@router.post("/logout-all")
def logout_all(request: Request, db: Session = Depends(get_db)):
    try:
        _, user = _require(db, request)
    except AuthError as err:
        return _error(err)
    auth.end_all_sessions(db, user.id)
    response = JSONResponse({"user": None})
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict", secure=settings.COOKIE_SECURE, httponly=True)
    return response


@router.post("/logout-others")
def logout_others(request: Request, db: Session = Depends(get_db)):
    try:
        _, user = _require(db, request)
    except AuthError as err:
        return _error(err)
    closed = auth.end_all_sessions(db, user.id, keep=request.cookies.get(COOKIE_NAME))
    return {"closed": closed}


@router.post("/account/delete")
def delete_account(payload: DeleteIn, request: Request, db: Session = Depends(get_db)):
    try:
        _, user = _require(db, request)
        if not auth.authenticate(db, user.email, payload.password):
            time.sleep(FAILURE_DELAY_SECONDS)
            raise AuthError("Пароль неверен", 400)
        auth.delete_account(db, user)
    except AuthError as err:
        return _error(err)
    response = JSONResponse({"user": None})
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict", secure=settings.COOKIE_SECURE, httponly=True)
    return response


def current_user(request: Request, db: Session) -> Optional[User]:
    found = auth.current(db, request.cookies.get(COOKIE_NAME))
    return None if found is None else found[1]
