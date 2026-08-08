"""HTTP-сессия для внешних API — с обходом прокси и своим корнем доверия.

Две вещи, из-за которых запросы к российским API падают на машине, где всё
остальное работает:

1. **Системный прокси.** VPN-клиенты прописывают `HTTPS_PROXY` в окружение, и
   requests начинает гонять трафик через туннель. Для MOEX и T-Invest это
   заканчивалось таймаутами на ответах больше пары десятков килобайт, поэтому
   `trust_env = False`.

2. **Корневой сертификат.** T-Invest отдаёт цепочку от УЦ Минцифры («Russian
   Trusted Root CA»), которого нет ни в системном хранилище, ни в certifi.
   Проверка падает с «self-signed certificate in certificate chain», хотя
   сертификат подлинный и подмены нет.

Второе лечится настройкой `EXTRA_CA_CERTS` — путём к PEM с дополнительными
корнями. Здесь он склеивается со штатным набором certifi во временный бандл:
так в репозитории лежит один маленький сертификат, а список международных УЦ
остаётся за certifi и обновляется вместе с зависимостями. Хранить в git копию
всего хранилища — значит заморозить её на дату коммита.

Важно: `trust_env = False` заодно отключает переменные `REQUESTS_CA_BUNDLE` и
`CURL_CA_BUNDLE` — задать бандл через окружение здесь не получится, только
через настройку.
"""
import hashlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import certifi
import requests

from app.config import settings

logger = logging.getLogger(__name__)

# Путь в настройках может быть относительным — считаем его от корня backend/,
# чтобы .env не зависел от того, из какой папки запущен процесс.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

_warned_missing: set = set()
_bundle_cache: Optional[str] = None


def _extra_ca_path() -> Optional[Path]:
    """Файл с дополнительными корнями из настроек, если он существует."""
    raw = (getattr(settings, "EXTRA_CA_CERTS", "") or "").strip()
    if not raw:
        return None

    path = Path(raw)
    if not path.is_absolute():
        path = _BACKEND_ROOT / path

    if not path.is_file():
        # Несуществующий путь — не повод падать: requests бросил бы невнятную
        # OSError на каждом запросе. Предупреждаем один раз и работаем со
        # штатным хранилищем.
        if raw not in _warned_missing:
            logger.warning(
                "EXTRA_CA_CERTS указывает на несуществующий файл: %s — "
                "используется стандартное хранилище сертификатов",
                path,
            )
            _warned_missing.add(raw)
        return None

    return path


def ca_bundle() -> str:
    """Путь к бандлу для проверки TLS: certifi плюс наши корни.

    Склеенный файл кладётся во временную папку и переиспользуется: имя зависит
    от содержимого обоих источников, поэтому обновление certifi или замена
    сертификата дают новый файл, а перезапуск процесса — тот же самый.
    """
    global _bundle_cache

    if _bundle_cache is not None and os.path.isfile(_bundle_cache):
        return _bundle_cache

    base = certifi.where()
    extra = _extra_ca_path()
    if extra is None:
        _bundle_cache = base
        return base

    base_bytes = Path(base).read_bytes()
    extra_bytes = extra.read_bytes()
    digest = hashlib.sha256(base_bytes + extra_bytes).hexdigest()[:16]
    merged = Path(tempfile.gettempdir()) / f"graham-ca-bundle-{digest}.pem"

    if not merged.is_file():
        # Перевод строки между файлами: без него «-----END CERTIFICATE-----»
        # склеится с началом следующего, и OpenSSL не разберёт бандл.
        merged.write_bytes(base_bytes.rstrip() + b"\n" + extra_bytes)
        logger.info(
            "Собран бандл сертификатов: certifi + %s → %s", extra.name, merged
        )

    _bundle_cache = str(merged)
    return _bundle_cache


def external_session(*, trust_env: bool = False) -> requests.Session:
    """Сессия для внешнего API: без прокси из окружения, с нашим бандлом."""
    session = requests.Session()
    session.trust_env = trust_env
    session.verify = ca_bundle()
    return session


def tls_hint(exc: BaseException) -> Optional[str]:
    """Подсказка для лога, если ошибка — про непроверяемую цепочку.

    Отличить «сервер лежит» от «не хватает корневого сертификата» по тексту
    SSLError тяжело, а действия разные: во втором случае ни токен, ни повтор
    запроса не помогут.
    """
    if not isinstance(exc, requests.exceptions.SSLError):
        return None
    return (
        "Не удалось проверить сертификат сервера. Обычно это значит, что "
        "цепочка выдана УЦ, которого нет в хранилище: положите его корень в "
        "backend/certs/ и укажите в EXTRA_CA_CERTS. Токен и повторный запрос "
        "тут не помогут — соединение рвётся до отправки запроса."
    )
