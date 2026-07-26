#!/usr/bin/env python3
"""
Интерактивное сохранение cookies e-disclosure (обход ServicePipe captcha).

Запуск на машине с GUI (DISPLAY):
  cd tools/edisclosure-scraper
  ../../backend/venv/bin/python save_cookies.py

Откроется Chromium → пройдите captcha вручную → когда увидите сайт,
скрипт сам сохранит .edisclosure_storage_state.json (или нажмите Enter в терминале).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from browser_session import STORAGE_STATE_PATH, is_challenge_html
from config import CONSOLIDATED_REPORT_TYPE, EDISCLOSURE_BASE_URL, USER_AGENT

CHECK_URL = (
    f"{EDISCLOSURE_BASE_URL}/portal/files.aspx"
    f"?id=30&type={CONSOLIDATED_REPORT_TYPE}"
)


def _looks_ok(html: str, url: str) -> bool:
    if is_challenge_html(html) and "<table" not in html:
        return False
    if "xpvnsulc" in url or "sp_rotated_captcha" in html.lower():
        return False
    return "<table" in html or "FileLoad.ashx" in html or "__VIEWSTATE" in html


def main() -> int:
    parser = argparse.ArgumentParser(description="Сохранить cookies e-disclosure")
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Секунд ожидания прохождения captcha (по умолчанию 300)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=STORAGE_STATE_PATH,
        help=f"Куда писать storage_state (по умолчанию {STORAGE_STATE_PATH})",
    )
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    print("Открываю Chromium (headed)…")
    print(f"URL проверки: {CHECK_URL}")
    print("Пройдите captcha в окне браузера. Скрипт сохранит cookies автоматически.")
    print("Либо нажмите Enter в этом терминале после успешного входа.\n")

    with sync_playwright() as pw:
        launch_kw = {
            "headless": False,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        }
        ep = pw.chromium.executable_path
        if ep:
            launch_kw["executable_path"] = ep
        browser = pw.chromium.launch(**launch_kw)
        context = browser.new_context(
            user_agent=USER_AGENT,
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1280, "height": 900},
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = context.new_page()
        page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=120_000)

        deadline = time.time() + args.timeout
        ok = False
        use_enter = sys.stdin.isatty()
        if use_enter:
            print("(можно нажать Enter после прохождения captcha)")
        else:
            print("(stdin не TTY — жду появления таблицы или таймаут)")

        while time.time() < deadline:
            if use_enter:
                try:
                    import select

                    if select.select([sys.stdin], [], [], 0)[0]:
                        sys.stdin.readline()
                        print("Enter — сохраняем текущее состояние…")
                        break
                except Exception:
                    pass

            try:
                html = page.content()
                url = page.url
            except Exception:
                time.sleep(1)
                continue

            if _looks_ok(html, url):
                print(f"Сайт доступен ({url[:80]}…) — сохраняю cookies.")
                ok = True
                break

            time.sleep(1.5)
        else:
            print("Таймаут ожидания captcha.", file=sys.stderr)

        # Если пользователь нажал Enter — проверим ещё раз
        if not ok:
            try:
                ok = _looks_ok(page.content(), page.url)
            except Exception:
                ok = False

        n_cookies = len(context.cookies())
        if n_cookies == 0 and not ok:
            browser.close()
            print("Cookies пустые — captcha, похоже, не пройдена. Ничего не сохраняю.", file=sys.stderr)
            return 2

        args.out.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(args.out))
        browser.close()

    print(f"Сохранено: {args.out}")
    print(f"Cookies: {n_cookies}")
    if not ok:
        print(
            "Внимание: таблица отчётов не подтверждена. "
            "Если captcha не пройдена — файл может не помочь. Запустите снова.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
