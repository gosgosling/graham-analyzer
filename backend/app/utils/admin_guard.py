"""Доступ: читать может любой, менять данные проекта — только администратор.

Одна прослойка на всё приложение, а не проверка в каждом эндпоинте: новый
эндпоинт на запись закрыт сам, его не надо помнить пометить.

Аккаунты сообщества (`/auth/*`) проверяют себя сами: там вход, регистрация
и личные настройки, роль не нужна.

Что закрыто без сессии пользователя с ролью admin:
  · любой запрос, меняющий данные (всё, кроме GET/HEAD/OPTIONS);
  · служебные разделы целиком, и на чтение тоже: там пути к папкам с PDF,
    очередь задач и прокси к внешним API — гость не должен через наш сервер
    гонять запросы к Мосбирже и T-Invest.

Защита от CSRF для всех запросов на запись, включая вход:
  · cookie сессии с SameSite=Strict — чужой сайт её не пошлёт;
  · заголовок Origin (или Referer) обязан быть из `ALLOWED_ORIGINS`;
  · обязательный заголовок X-Requested-With: форма с чужого сайта его
    поставить не может, а скрипт — только после разрешения CORS.
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import allowed_origins, settings
from app.database import SessionLocal
from app.models.user import ROLE_ADMIN
from app.services.auth import COOKIE_NAME, current

logger = logging.getLogger("auth")

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "graham-analyzer"

# Служебное: закрыто и на чтение.
ADMIN_PREFIXES = (
    "/admin", "/mass-parse", "/bonds", "/securities",
    "/market/shares", "/market/dividends", "/market/price", "/market/fx",
    "/disclosure/summary", "/disclosure/coverage", "/disclosure/sync", "/disclosure/parse-jobs",
    "/companies/sync",
)
# Аккаунты: роль не нужна, но защиту от CSRF проходят.
AUTH_PREFIX = "/auth"


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def needs_admin(method: str, path: str) -> bool:
    if _matches(path, AUTH_PREFIX):
        return False
    if method.upper() not in SAFE_METHODS:
        return True
    return any(_matches(path, p) for p in ADMIN_PREFIXES)


def needs_csrf(method: str) -> bool:
    return method.upper() not in SAFE_METHODS


def origin_allowed(origin: Optional[str], referer: Optional[str]) -> bool:
    allowed = set(allowed_origins())
    if origin:
        return origin.rstrip("/") in allowed
    if referer:
        parts = urlsplit(referer)
        return f"{parts.scheme}://{parts.netloc}" in allowed
    return False


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail},
                        headers={"Cache-Control": "no-store"})


class AdminGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method, path = request.method, request.url.path

        if needs_csrf(method):
            if request.headers.get(CSRF_HEADER) != CSRF_VALUE or not origin_allowed(
                request.headers.get("origin"), request.headers.get("referer"),
            ):
                logger.warning("CSRF: отклонён %s %s с %s", method, path, client_ip(request))
                return _deny(403, "Запрос отклонён: не с нашей страницы")

        if needs_admin(method, path):
            db = SessionLocal()
            try:
                found = current(db, request.cookies.get(COOKIE_NAME))
                user_id, role = (found[1].id, found[1].role) if found else (None, None)
            finally:
                db.close()
            if user_id is None:
                return _deny(401, "Нужен вход администратора")
            if role != ROLE_ADMIN:
                logger.warning("не админ: %s %s от пользователя %s", method, path, user_id)
                return _deny(403, "Недостаточно прав")
            if needs_csrf(method):
                logger.info("admin %s %s (пользователь %s, %s)", method, path, user_id, client_ip(request))

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Заголовки безопасности на ответах API."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"
        if settings.COOKIE_SECURE:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
