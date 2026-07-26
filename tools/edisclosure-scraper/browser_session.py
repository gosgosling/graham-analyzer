"""Общий Playwright-контекст для e-disclosure (cookies / Storage State)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from config import USER_AGENT

logger = logging.getLogger(__name__)

STORAGE_STATE_PATH = Path(__file__).resolve().parent / ".edisclosure_storage_state.json"

_lock = threading.Lock()
_pw = None
_browser = None
_context = None


class ServicePipeBlockedError(RuntimeError):
    """ServicePipe показал captcha / challenge без таблицы отчётов."""


def is_challenge_html(html: str) -> bool:
    low = html.lower()
    if "js-challenge" in low or "servicepipe.ru" in low:
        return True
    if "sp_rotated_captcha" in low or "captcha-wrap" in low:
        return True
    if "/xpvnsulc/" in low and "<table" not in low:
        return True
    return False


def _launch_context(storage_state: Optional[str] = None):
    global _pw, _browser, _context
    from playwright.sync_api import sync_playwright

    _pw = sync_playwright().start()
    launch_kw = {
        "headless": True,
        "args": [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    }
    ep = _pw.chromium.executable_path
    if ep:
        launch_kw["executable_path"] = ep
    _browser = _pw.chromium.launch(**launch_kw)
    ctx_kw = {
        "user_agent": USER_AGENT,
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
        "viewport": {"width": 1366, "height": 768},
    }
    if storage_state and Path(storage_state).is_file():
        ctx_kw["storage_state"] = storage_state
        logger.info("Playwright: загружен storage_state %s", storage_state)
    _context = _browser.new_context(**ctx_kw)
    _context.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )


def get_context(*, force_new: bool = False):
    """Вернуть долгоживущий BrowserContext (поток должен быть один)."""
    global _context
    with _lock:
        if force_new:
            close_session()
        if _context is None:
            state = str(STORAGE_STATE_PATH) if STORAGE_STATE_PATH.is_file() else None
            _launch_context(state)
        return _context


def save_storage_state() -> None:
    with _lock:
        if _context is None:
            return
        try:
            _context.storage_state(path=str(STORAGE_STATE_PATH))
            logger.info("Playwright: storage_state сохранён → %s", STORAGE_STATE_PATH)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось сохранить storage_state: %s", exc)


def close_session() -> None:
    global _pw, _browser, _context
    with _lock:
        try:
            if _context is not None:
                _context.close()
        except Exception:
            pass
        try:
            if _browser is not None:
                _browser.close()
        except Exception:
            pass
        try:
            if _pw is not None:
                _pw.stop()
        except Exception:
            pass
        _pw = _browser = _context = None
