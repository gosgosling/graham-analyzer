#!/usr/bin/env python3
"""Собирает полный JSON: company_ids.json + edisclosure_ids_generated.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent
MAPPING = ROOT / "company_ids.json"
GENERATED = ROOT / "edisclosure_ids_generated.json"
OUT = ROOT / "edisclosure_ids_complete.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--db-only",
        action="store_true",
        help="Оставить только тикеры из текущей выгрузки БД (db_client)",
    )
    args = ap.parse_args()

    db_tickers: set[str] | None = None
    if args.db_only:
        from db_client import get_companies_full_from_db

        db_tickers = {c.ticker.upper() for c in get_companies_full_from_db()}

    merged: dict[str, dict] = {}
    if MAPPING.exists():
        raw = json.loads(MAPPING.read_text(encoding="utf-8"))
        for k, v in raw.items():
            if k.startswith("_"):
                continue
            ku = k.upper()
            if db_tickers is not None and ku not in db_tickers:
                continue
            if isinstance(v, dict) and isinstance(v.get("id"), int):
                merged[ku] = {"id": v["id"], "name": v.get("name", "")}
    if GENERATED.exists():
        gen = json.loads(GENERATED.read_text(encoding="utf-8"))
        for k, row in gen.items():
            if not isinstance(row, dict):
                continue
            ku = k.upper()
            if db_tickers is not None and ku not in db_tickers:
                continue
            eid = row.get("id")
            if isinstance(eid, int):
                merged[ku] = {"id": eid, "name": row.get("name") or row.get("moex_title") or ""}
    OUT.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Записано {len(merged)} тикеров в {OUT}")


if __name__ == "__main__":
    main()
