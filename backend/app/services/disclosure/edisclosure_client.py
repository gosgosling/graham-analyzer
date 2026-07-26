"""Обёртка над tools/edisclosure-scraper (Playwright listing + download)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SCRAPER_DIR = (
    Path(__file__).resolve().parents[4] / "tools" / "edisclosure-scraper"
)
# Path: backend/app/services/disclosure -> parents[0]=disclosure ... parents[3]=backend, parents[4]=repo root
# __file__ = .../backend/app/services/disclosure/edisclosure_client.py
# parents[0]=disclosure, [1]=services, [2]=app, [3]=backend, [4]=repo root ✓


def _ensure_scraper_path() -> Path:
    root = Path(__file__).resolve().parents[4]
    scraper = root / "tools" / "edisclosure-scraper"
    if not scraper.is_dir():
        # fallback: cwd-relative
        alt = Path.cwd().parent / "tools" / "edisclosure-scraper"
        if alt.is_dir():
            scraper = alt
    if str(scraper) not in sys.path:
        sys.path.insert(0, str(scraper))
    return scraper


def load_edisclosure_mapping() -> dict[str, int]:
    scraper = _ensure_scraper_path()
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
    _ensure_scraper_path()
    from scraper import fetch_all_reports  # type: ignore[import-not-found]

    entries = fetch_all_reports(edisclosure_id, ticker)
    return [e.to_dict() for e in entries]


def close_browser_session() -> None:
    _ensure_scraper_path()
    try:
        from browser_session import close_session  # type: ignore[import-not-found]

        close_session()
    except Exception:  # noqa: BLE001
        pass


def download_company_reports(
    ticker: str, report_dicts: list[dict[str, Any]]
) -> dict[str, str]:
    """Скачать выбранные периоды. report_dicts — как to_dict() ReportEntry."""
    _ensure_scraper_path()
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
    _ensure_scraper_path()
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
