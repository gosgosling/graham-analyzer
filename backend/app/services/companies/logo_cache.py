"""Логотипы компаний — свои копии вместо ссылок на CDN Т-Банка.

Раньше страница брала логотип прямо с `invest-brands.cdn-tinkoff.ru`, и
доступность чужого CDN становилась доступностью нашей страницы: когда
T-Invest лежал из-за атак на дата-центры Яндекса, вместо логотипов были бы
пустые места у всех 156 компаний. Теперь картинка скачивается один раз и
отдаётся с нашего сервера (`GET /logos/{тикер}.png`); CDN остаётся запасным
вариантом во фронтенде.

Кэш заполняется лениво — при первом запросе логотипа — и целиком командой
`python -m scripts.cache_logos`. Не нашедшийся логотип помечается файлом
`.miss` на сутки, чтобы каждый показ страницы не ходил на CDN заново.

Файлы в гит не кладутся: это чужие товарные знаки, а не код проекта.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Iterable, Optional

import requests

from app.config import BASE_DIR, settings
from app.utils.http_session import external_session
from app.utils.source_health import breaker
from app.utils.tinkoff_client import _cdn_logo_url_from_logo_name, _logo_cdn_urls_for_sync

logger = logging.getLogger(__name__)

CDN = breaker("tinvest_cdn", "CDN логотипов Т-Банка")

MISS_TTL = 24 * 3600          # секунд до повторной попытки ненайденного
MIN_BYTES = 200               # меньше — не картинка, а заглушка или ошибка
_TICKER = re.compile(r"^[A-Z0-9._-]{1,20}$")


def cache_dir() -> Path:
    path = Path(settings.LOGO_CACHE_DIR) if settings.LOGO_CACHE_DIR else BASE_DIR / "data" / "logos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key(ticker: str) -> Optional[str]:
    key = str(ticker or "").strip().upper()
    return key if _TICKER.match(key) else None


def cached_path(ticker: str) -> Optional[Path]:
    key = _key(ticker)
    if key is None:
        return None
    path = cache_dir() / f"{key}.png"
    return path if path.is_file() else None


_SIZED = re.compile(r"x(160|320|640)\.(png|webp|jpe?g|svg)$")
_EXT = re.compile(r"\.(png|webp|jpe?g|svg)$", re.IGNORECASE)


def _sized(url: str) -> list:
    """CDN отдаёт только объекты с суффиксом размера: `sber3.png` → 403, `sber3x160.png` — 200.

    То же правило, что во фронтенде (`withSizeSuffixes`): суффикс вставляется
    в имя из API перед расширением.
    """
    path = url.split("?", 1)[0]
    if "invest-brands.cdn-tinkoff.ru" not in path.lower() or _SIZED.search(path):
        return [url]
    match = _EXT.search(path)
    base, ext = (path[: match.start()], match.group(0)) if match else (path.rstrip("/"), ".png")
    return [f"{base}x160{ext}", f"{base}x640{ext}", url]


def candidates(company) -> list:
    """Ссылки на CDN по порядку: из API (с суффиксом размера), затем по ISIN и тикеру."""
    out: list = []
    raw = (getattr(company, "brand_logo_url", None) or "").strip()
    if raw:
        for url in _sized(_cdn_logo_url_from_logo_name(raw)):
            if url not in out:
                out.append(url)
    for url in _logo_cdn_urls_for_sync(getattr(company, "isin", None), getattr(company, "ticker", None)):
        if url not in out:
            out.append(url)
    return [u for u in out if u]


def _download(url: str) -> Optional[bytes]:
    # Разрешение имён здесь периодически отваливается на секунду-другую —
    # без повтора один такой сбой ставил весь CDN на паузу.
    for attempt in range(3):
        try:
            response = external_session().get(url, timeout=8)
            break
        except requests.exceptions.ConnectionError as exc:
            if attempt == 2:
                CDN.failure(exc)
                return None
            time.sleep(1 + attempt)
        except requests.exceptions.RequestException as exc:
            CDN.failure(exc)
            return None
    CDN.success()
    kind = response.headers.get("Content-Type", "")
    if response.status_code != 200 or not kind.startswith("image/") or len(response.content) < MIN_BYTES:
        return None
    return response.content


def ensure(company) -> Optional[Path]:
    """Путь к локальной копии логотипа; скачивает, если её ещё нет."""
    key = _key(getattr(company, "ticker", ""))
    if key is None:
        return None
    folder = cache_dir()
    target, miss = folder / f"{key}.png", folder / f"{key}.miss"
    if target.is_file():
        return target
    if miss.is_file() and time.time() - miss.stat().st_mtime < MISS_TTL:
        return None
    if not CDN.available():
        return None
    for url in candidates(company):
        body = _download(url)
        if body is None:
            if not CDN.available():
                return None          # CDN лёг посреди перебора — промах не записываем
            continue
        tmp = folder / f".{key}.{os.getpid()}.tmp"
        tmp.write_bytes(body)
        tmp.replace(target)
        miss.unlink(missing_ok=True)
        return target
    miss.touch()
    return None


def cache_all(companies: Iterable, wait: bool = True) -> dict:
    """Докачать недостающие логотипы. → {"cached": n, "missing": [тикеры]}."""
    cached, missing = 0, []
    for company in companies:
        if cached_path(company.ticker):
            cached += 1
            continue
        # Пакетный прогон ждёт конца паузы, а не записывает всех в «не нашли».
        # Планировщику ждать нельзя — он просто пропускает до следующего раза.
        if not wait and not CDN.available():
            break
        waited = 0
        while wait and not CDN.available() and waited < 120:
            time.sleep(5)
            waited += 5
        if ensure(company) is not None:
            cached += 1
        else:
            missing.append(company.ticker)
    return {"cached": cached, "missing": missing}


def status() -> dict:
    folder = cache_dir()
    return {"dir": str(folder), "files": len(list(folder.glob("*.png")))}
