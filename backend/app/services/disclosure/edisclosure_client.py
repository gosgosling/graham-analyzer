"""Обёртка над tools/edisclosure-scraper (Playwright listing + download)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

# Каталог скрапера считается от расположения этого файла, а не от текущего
# рабочего каталога: сервер запускают и из backend/, и из корня, и из systemd.
# Раньше здесь было три догадки подряд (parents[4], root/tools, cwd().parent),
# и приложение вело себя по-разному в зависимости от места запуска.
#
# BASE_DIR — корень репозитория, тот же, от которого config.py читает .env.
SCRAPER_DIR = BASE_DIR / "tools" / "edisclosure-scraper"


def ensure_scraper_importable() -> Path:
    """Делает модули скрапера импортируемыми и возвращает его каталог.

    Дефис в имени каталога не даёт оформить его обычным пакетом, поэтому путь
    добавляется в `sys.path`. Единственное место, где это делается: тесты и
    сервисы вызывают эту функцию, а не повторяют вставку у себя.

    Raises:
        FileNotFoundError: каталога нет — сразу и с понятным текстом, вместо
        `ModuleNotFoundError: scraper` из глубины импорта.
    """
    if not SCRAPER_DIR.is_dir():
        raise FileNotFoundError(
            f"Не найден каталог скрапера: {SCRAPER_DIR}. "
            "Он часть репозитория — проверьте, что backend запущен из рабочей копии."
        )
    if str(SCRAPER_DIR) not in sys.path:
        sys.path.insert(0, str(SCRAPER_DIR))
    return SCRAPER_DIR



def load_edisclosure_mapping() -> dict[str, int]:
    scraper = ensure_scraper_importable()
    mapping_file = scraper / "company_ids.json"
    with open(mapping_file, encoding="utf-8") as f:
        raw = json.load(f)
    out: dict[str, int] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(value.get("id"), int):
            out[key.upper()] = value["id"]
    return out


def fetch_company_reports(edisclosure_id: int, ticker: str) -> list[dict[str, Any]]:
    """Listing всех консолидированных периодов → list[dict]."""
    ensure_scraper_importable()
    from scraper import fetch_all_reports  # type: ignore[import-not-found]

    entries = fetch_all_reports(edisclosure_id, ticker)
    return [e.to_dict() for e in entries]


def close_browser_session() -> None:
    ensure_scraper_importable()
    try:
        from browser_session import close_session  # type: ignore[import-not-found]

        close_session()
    except Exception:  # noqa: BLE001
        pass


def download_company_reports(
    ticker: str, report_dicts: list[dict[str, Any]]
) -> dict[str, str]:
    """Скачать выбранные периоды. report_dicts — как to_dict() ReportEntry."""
    ensure_scraper_importable()
    from scraper import ReportEntry  # type: ignore[import-not-found]
    from downloader import download_reports  # type: ignore[import-not-found]

    reports = []
    for d in report_dicts:
        reports.append(
            ReportEntry(
                doc_type=d.get("doc_type") or "",
                period=d.get("period") or d.get("period_label") or "",
                year=int(d["fiscal_year"]),
                fiscal_year=int(d["fiscal_year"]),
                period_type=d["period_type"],
                fiscal_quarter=d.get("fiscal_quarter"),
                period_key=d["period_key"],
                interim_rank=int(d.get("interim_rank") or 0),
                file_url=d["file_url"],
                file_label=d.get("file_label") or "zip",
                published_at=d.get("published_at"),
            )
        )
    return download_reports(ticker, reports)


def filter_coverage(entries: list[dict[str, Any]], *, min_annual_year: int = 2010) -> list[dict[str, Any]]:
    ensure_scraper_importable()
    from period_parse import filter_coverage_entries  # type: ignore[import-not-found]
    from types import SimpleNamespace

    objs = [SimpleNamespace(**e) for e in entries]
    kept = filter_coverage_entries(objs, min_annual_year=min_annual_year)
    keys = {(o.period_type, o.fiscal_year, getattr(o, "fiscal_quarter", None)) for o in kept}
    return [
        e
        for e in entries
        if (e["period_type"], e["fiscal_year"], e.get("fiscal_quarter")) in keys
    ]
