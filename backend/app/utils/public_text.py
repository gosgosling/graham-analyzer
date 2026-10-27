"""Служебные пометки в текстах — только для администратора.

Часть отчётов внесена вручную через ассистента, и в заметках к ним так и
записано: «12.10.2026, Claude: перенесено вручную из форм МСФО…». В допущениях
рынка — «предварительные суждения Claude, не пользователя». Для журнала
работы это нужная пометка: кто и как внёс число. Посетителю сайта она ничего
не говорит и только сбивает: автор расчёта — владелец сайта.

Поэтому гость получает те же тексты без имени ассистента, администратор — как
есть. Очистка — на выходе API, одной прослойкой: тексты лежат в нескольких
таблицах и уходят из разных эндпоинтов, и помнить о каждом не нужно.

Прослойка стоит внутри ETag: хэш считается по уже очищенному телу, так что у
гостя и администратора он разный, и чужой ответ 304-м не подтвердится.
"""
from __future__ import annotations

import re

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.database import SessionLocal
from app.models.user import ROLE_ADMIN
from app.services.auth import COOKIE_NAME, current

# Порядок важен: сначала устойчивые обороты, в конце — одиночное имя.
_RULES: tuple[tuple[re.Pattern, str], ...] = (
    # «12.10.2026, Claude: перенесено…» → «12.10.2026: перенесено…»
    (re.compile(r"(\d{2}\.\d{2}\.\d{4}),?\s+Claude:"), r"\1:"),
    # «Внесено Claude 12.10.2026» → «Внесено 12.10.2026»
    (re.compile(r"Внесено Claude\s+"), "Внесено "),
    # «предварительные суждения Claude, не пользователя» → «предварительные суждения автора»
    (re.compile(r"суждения Claude,\s*не пользователя"), "суждения автора"),
    (re.compile(r"\s*\(?\bClaude\b\)?,?"), ""),
)

_NEEDLE = b"Claude"


def public_text(value: str) -> str:
    """Текст без имени ассистента — каким его видит гость."""
    if "Claude" not in value:
        return value
    for pattern, replacement in _RULES:
        value = pattern.sub(replacement, value)
    return value


def _is_admin(scope: Scope) -> bool:
    cookie = Headers(scope=scope).get("cookie") or ""
    raw = None
    for part in cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE_NAME:
            raw = value
            break
    if not raw:
        return False
    db = SessionLocal()
    try:
        found = current(db, raw)
        return bool(found and found[1].role == ROLE_ADMIN)
    finally:
        db.close()


class PublicTextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET" or scope["path"].startswith("/auth"):
            await self.app(scope, receive, send)
            return

        admin: bool | None = None
        start: Message | None = None
        chunks: list[bytes] = []
        passthrough = False

        async def wrapped(message: Message) -> None:
            nonlocal start, passthrough, admin
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                if (not headers.get("content-type", "").startswith("application/json")
                        or "content-encoding" in headers):
                    passthrough = True
                    await send(message)
                else:
                    start = message
                return
            if passthrough or start is None:
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            if _NEEDLE in body:
                if admin is None:
                    admin = _is_admin(scope)
                if not admin:
                    body = public_text(body.decode("utf-8")).encode("utf-8")
            headers = MutableHeaders(raw=start["headers"])
            headers["content-length"] = str(len(body))
            await send(start)
            await send({"type": "http.response.body", "body": body, "more_body": False})

        await self.app(scope, receive, wrapped)
