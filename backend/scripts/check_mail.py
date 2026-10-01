"""Проверить почту: отправить пробное письмо.

    python -m scripts.check_mail you@example.ru

Берёт настройки SMTP из .env. Пароль не печатается.
"""
from __future__ import annotations

import sys

from app.config import settings
from app.services import mailer


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    if not mailer.configured():
        print("SMTP не настроен: заполните SMTP_HOST и SMTP_FROM в .env.", file=sys.stderr)
        return 1
    print(f"Сервер {settings.SMTP_HOST}:{settings.SMTP_PORT}, вход как {settings.SMTP_USER or '—'}, "
          f"пароль {'задан' if settings.SMTP_PASSWORD else 'НЕ задан'}, отправитель {settings.SMTP_FROM}")
    try:
        mailer.send(sys.argv[1], "Проверка почты — Graham Analyzer",
                    "Если вы читаете это письмо, почта сайта настроена правильно.", raise_errors=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Не отправилось: {exc}", file=sys.stderr)
        return 1
    print("Отправлено. Проверьте ящик (и «Спам»).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
