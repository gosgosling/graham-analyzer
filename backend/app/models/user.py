"""Аккаунты сообщества.

Читать сайт можно без аккаунта — аккаунт нужен, чтобы сообщество могло
однажды что-то делать: сохранять списки, оставлять заметки. Роль `admin`
открывает правку данных проекта; у остальных — `user`.

Почта хранится в нижнем регистре и уникальна. Пароль — только хэшем
(scrypt). Подтверждение почты — отдельная отметка: войти можно и без неё,
но то, что потом потребует доверия к адресу, будет её проверять.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

ROLE_USER = "user"
ROLE_ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=ROLE_USER)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Когда менялся пароль: сессии, открытые раньше, считаются недействительными.
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Согласие на обработку ПДн (152-ФЗ, ст. 9): когда и какую редакцию принял.
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class UserSession(Base):
    """Серверная сессия. В cookie — случайный идентификатор, здесь — его SHA-256."""

    __tablename__ = "user_sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class AuthToken(Base):
    """Одноразовые ссылки из писем: подтверждение почты, сброс пароля, смена почты.

    В письмо уходит случайная строка, здесь — её SHA-256. Ссылка живёт
    недолго и гасится после первого использования.
    """

    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)  # verify | reset | email
    # Для смены почты: новый адрес. Меняется, только когда по ссылке перешли с него.
    new_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
