#!/usr/bin/env python3
"""Выгрузить эталонные отчёты LKOH/NVTK из Postgres в tests/fixtures/golden/.

Запуск из каталога backend:
  venv/bin/python scripts/export_golden_reports.py

DATABASE_URL берётся из окружения или дефолт docker-compose.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

FIELDS = [
    "fiscal_year", "period_type", "accounting_standard", "consolidated",
    "currency", "exchange_rate", "report_date", "filing_date",
    "shares_outstanding", "shares_weighted_avg",
    "revenue", "net_income", "net_income_reported",
    "total_assets", "current_assets", "total_liabilities", "current_liabilities",
    "equity", "cash_and_equivalents", "debt",
    "dividends_per_share", "dividends_paid",
    "special_dividends_per_share", "special_dividends_note",
    "operating_cash_flow", "capex", "lease_principal", "lease_interest",
    "debt_principal", "depreciation_amortization", "verified_by_analyst",
]

TARGETS = [
    ("LKOH", 2024), ("LKOH", 2023), ("LKOH", 2021),
    ("NVTK", 2025), ("NVTK", 2024), ("NVTK", 2023),
    ("AFLT", 2025), ("AFLT", 2024), ("AFLT", 2023),
    ("ALRS", 2025), ("ALRS", 2024), ("ALRS", 2023),
]


def main() -> None:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://graham_user:12345678@localhost:5432/graham_analyzer",
    )
    out_dir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "golden"
    out_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url)
    sql = text(
        f"""
        SELECT c.ticker, c.name, c.sector, fr.id AS report_id,
               {', '.join('fr.' + f for f in FIELDS)}
        FROM companies c
        JOIN financial_reports fr ON fr.company_id = c.id
        WHERE c.ticker = :ticker
          AND fr.fiscal_year = :year
          AND fr.period_type = 'ANNUAL'
          AND fr.accounting_standard = 'IFRS'
          AND fr.verified_by_analyst IS TRUE
        ORDER BY fr.id
        LIMIT 1
        """
    )

    index = []
    with engine.connect() as conn:
        for ticker, year in TARGETS:
            row = conn.execute(sql, {"ticker": ticker, "year": year}).mappings().first()
            if not row:
                print(f"SKIP {ticker} {year}: not found")
                continue
            data = dict(row)
            for k, v in list(data.items()):
                if hasattr(v, "isoformat"):
                    data[k] = v.isoformat()
                elif hasattr(v, "as_tuple"):
                    data[k] = float(v)
            if data.get("revenue") is None or data.get("equity") is None:
                print(f"SKIP {ticker} {year}: incomplete")
                continue
            fname = f"{ticker}_{year}_IFRS_annual.json"
            (out_dir / fname).write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            index.append(
                {"ticker": ticker, "year": year, "file": fname, "report_id": data["report_id"]}
            )
            print(f"OK {fname}")

    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(index)} golden reports → {out_dir}")


if __name__ == "__main__":
    main()
