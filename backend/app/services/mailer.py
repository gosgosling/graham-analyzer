"""Письма: подтверждение почты и сброс пароля.

Без настроенного SMTP письмо не уходит, а пишется в журнал сервера вместе со
ссылкой — так можно пройти весь путь локально. На сервере SMTP обязателен:
без него никто, кроме администратора с доступом к логам, не восстановит
пароль.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("mail")


def configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def send(to: str, subject: str, text: str, raise_errors: bool = False) -> None:
    """Отправить письмо. Ошибка отправки не роняет запрос пользователя —
    пишется в журнал; `raise_errors` — для проверочного скрипта."""
    if not configured():
        logger.warning("SMTP не настроен — письмо не отправлено.\nКому: %s\nТема: %s\n%s", to, subject, text)
        return
    message = EmailMessage()
    message["From"] = settings.SMTP_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    context = ssl.create_default_context()
    try:
        # 465 — TLS с первого байта, 587 — обычное соединение и STARTTLS.
        if settings.SMTP_PORT == 465:
            smtp = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15, context=context)
        else:
            smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
        with smtp:
            if settings.SMTP_PORT != 465 and settings.SMTP_STARTTLS:
                smtp.starttls(context=context)
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001 — письмо не должно ронять запрос
        logger.error("Письмо на %s не отправлено: %s", to, exc)
        if raise_errors:
            raise
