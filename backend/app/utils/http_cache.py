"""ETag для ответов API: не пересылать то, что у браузера уже есть.

Ответ GET в JSON получает ETag — короткий хэш тела — и `Cache-Control:
private, no-cache`: браузер хранит ответ у себя и перед каждым использованием
спрашивает сервер, не изменился ли он. Если нет, сервер отвечает 304 без тела.
Для цен по компании (полмегабайта) это разница между мегабайтом трафика на
каждый заход и парой сотен байт.

`private` — хранить можно только браузеру, не промежуточным прокси: часть
ответов зависит от того, кто вошёл. ETag считается по фактическому телу, так
что у администратора и гостя он разный, и чужой ответ 304-м не подтвердится.
Проверка доступа стоит снаружи этой прослойки — до хэша запрос без прав не
доходит. Разделы входа (`/auth`) не трогаем совсем: там `no-store`.
"""
from __future__ import annotations

import hashlib

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SKIP_PREFIXES = ("/auth",)


def etag_for(body: bytes) -> str:
    # Слабый ETag (W/): сжатие поверх меняет байты, а смысл ответа — нет.
    return 'W/"%s"' % hashlib.blake2b(body, digest_size=12).hexdigest()


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    bare = etag.removeprefix("W/")
    return any(tag.strip().removeprefix("W/") == bare for tag in if_none_match.split(","))


class ETagMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "GET"
            or scope["path"].startswith(SKIP_PREFIXES)
        ):
            await self.app(scope, receive, send)
            return

        if_none_match = Headers(scope=scope).get("if-none-match")
        start: Message | None = None
        chunks: list[bytes] = []
        passthrough = False

        async def wrapped(message: Message) -> None:
            nonlocal start, passthrough
            if message["type"] == "http.response.start":
                headers = Headers(raw=message["headers"])
                if (
                    message["status"] != 200
                    or not headers.get("content-type", "").startswith("application/json")
                    or "etag" in headers
                    or "content-encoding" in headers
                ):
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
            etag = etag_for(body)
            headers = MutableHeaders(raw=start["headers"])
            headers["ETag"] = etag
            if "cache-control" not in headers:
                headers["Cache-Control"] = "private, no-cache"
            if _matches(if_none_match, etag):
                del headers["content-length"]
                del headers["content-type"]
                await send({**start, "status": 304, "headers": headers.raw})
                await send({"type": "http.response.body", "body": b""})
                return
            await send({**start, "headers": headers.raw})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, wrapped)
