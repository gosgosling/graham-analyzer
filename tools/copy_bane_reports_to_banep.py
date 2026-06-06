#!/usr/bin/env python3
"""
Копирует годовые отчёты BANE → BANEP: те же финансовые показатели,
отдельные price_per_share, shares_outstanding и dividends_per_share (MOEX).

Запуск:
  python3 tools/copy_bane_reports_to_banep.py [--dry-run]

Требования: docker (контейнер graham_postgres), доступ к MOEX API.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.utils.moex_client import (  # noqa: E402
    get_closing_price_on_or_before,
    get_dividends_for_period,
)

PG_CONTAINER = "graham_postgres"
PG_USER = "graham_user"
PG_DB = "graham_analyzer"

BANE_TICKER = "BANE"
BANEP_TICKER = "BANEP"

SHARES_FULL_EMISSION = 34_622_686
SHARES_IN_CIRCULATION = 29_788_357

INSERT_COLUMNS = [
    "company_id",
    "period_type",
    "fiscal_year",
    "fiscal_quarter",
    "accounting_standard",
    "consolidated",
    "report_date",
    "filing_date",
    "source",
    "report_type",
    "price_per_share",
    "price_at_filing",
    "shares_outstanding",
    "revenue",
    "net_income",
    "net_income_reported",
    "total_assets",
    "current_assets",
    "total_liabilities",
    "current_liabilities",
    "equity",
    "dividends_per_share",
    "dividends_paid",
    "currency",
    "exchange_rate",
    "operating_cash_flow",
    "capex",
    "depreciation_amortization",
    "has_preferred_shares",
    "preferred_share_dividends",
    "auto_extracted",
    "verified_by_analyst",
    "extraction_notes",
]


def psql_json(sql: str) -> list[dict]:
    cmd = [
        "docker", "exec", PG_CONTAINER,
        "psql", "-U", PG_USER, "-d", PG_DB,
        "-t", "-A", "-c", sql,
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    if not out:
        return []
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def psql_exec(sql: str) -> None:
    subprocess.run(
        [
            "docker", "exec", "-i", PG_CONTAINER,
            "psql", "-U", PG_USER, "-d", PG_DB,
            "-v", "ON_ERROR_STOP=1",
        ],
        input=sql,
        text=True,
        check=True,
    )


def shares_for_year(fiscal_year: int) -> int:
    return SHARES_FULL_EMISSION if fiscal_year <= 2013 else SHARES_IN_CIRCULATION


def moex_price(ticker: str, report_date: date) -> float | None:
    row = get_closing_price_on_or_before(ticker, report_date, lookback_days=15)
    return float(row["price"]) if row else None


def moex_dividends(ticker: str, fiscal_year: int) -> tuple[float | None, bool]:
    data = get_dividends_for_period(ticker, fiscal_year, "annual")
    if not data:
        return None, False
    total = float(data.get("total") or 0)
    if total <= 0:
        return None, False
    return total, True


def sql_literal(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return "'" + str(val).replace("'", "''") + "'"


def build_values(src: dict, banep_id: int) -> dict[str, object]:
    fy = int(src["fiscal_year"])
    rd = date.fromisoformat(src["report_date"])
    price = moex_price(BANEP_TICKER, rd)
    dps, div_paid = moex_dividends(BANEP_TICKER, fy)
    shares = shares_for_year(fy)

    return {
        "company_id": banep_id,
        "period_type": src["period_type"],
        "fiscal_year": fy,
        "fiscal_quarter": src.get("fiscal_quarter"),
        "accounting_standard": src["accounting_standard"],
        "consolidated": src.get("consolidated", True),
        "report_date": src["report_date"],
        "filing_date": src.get("filing_date"),
        "source": src["source"],
        "report_type": src.get("report_type", "general"),
        "price_per_share": price,
        "price_at_filing": None,
        "shares_outstanding": shares,
        "revenue": src.get("revenue"),
        "net_income": src.get("net_income"),
        "net_income_reported": src.get("net_income_reported"),
        "total_assets": src.get("total_assets"),
        "current_assets": src.get("current_assets"),
        "total_liabilities": src.get("total_liabilities"),
        "current_liabilities": src.get("current_liabilities"),
        "equity": src.get("equity"),
        "dividends_per_share": dps,
        "dividends_paid": div_paid,
        "currency": src.get("currency") or "RUB",
        "exchange_rate": src.get("exchange_rate"),
        "operating_cash_flow": src.get("operating_cash_flow"),
        "capex": src.get("capex"),
        "depreciation_amortization": src.get("depreciation_amortization"),
        "has_preferred_shares": False,
        "preferred_share_dividends": None,
        "auto_extracted": False,
        "verified_by_analyst": True,
        "extraction_notes": (
            f"Скопировано с отчётов {BANE_TICKER}; цена и дивиденды — {BANEP_TICKER} (MOEX); "
            f"акции — {shares:,} шт."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    companies = psql_json(
        "SELECT json_build_object('id', id, 'ticker', ticker) "
        "FROM companies WHERE ticker IN ('BANE', 'BANEP') ORDER BY ticker;"
    )
    by_ticker = {c["ticker"]: int(c["id"]) for c in companies}
    if BANE_TICKER not in by_ticker or BANEP_TICKER not in by_ticker:
        print("BANE/BANEP не найдены в БД", file=sys.stderr)
        sys.exit(1)

    banep_id = by_ticker[BANEP_TICKER]
    bane_id = by_ticker[BANE_TICKER]

    cnt_row = psql_json(
        f"SELECT json_build_object('c', COUNT(*)::int) "
        f"FROM financial_reports WHERE company_id = {banep_id};"
    )
    if cnt_row and cnt_row[0]["c"] > 0:
        print(f"У {BANEP_TICKER} уже {cnt_row[0]['c']} отчёт(ов). Прерывание.")
        sys.exit(1)

    src_rows = psql_json(
        f"SELECT row_to_json(r) FROM financial_reports r "
        f"WHERE company_id = {bane_id} ORDER BY report_date;"
    )
    print(f"Копирование {len(src_rows)} отчётов: {BANE_TICKER} → {BANEP_TICKER}")

    sql_parts: list[str] = [
        "BEGIN;",
        f"UPDATE companies SET is_preferred_share = true WHERE id = {banep_id};",
    ]

    for src in src_rows:
        vals = build_values(src, banep_id)

        fy = int(src["fiscal_year"])
        print(
            f"  {fy}: shares={vals['shares_outstanding']:,} "
            f"price={vals['price_per_share']} div={vals['dividends_per_share']} "
            f"paid={vals['dividends_paid']}"
        )

        if not args.dry_run:
            col_list = ", ".join(INSERT_COLUMNS)
            val_list = ", ".join(sql_literal(vals[c]) for c in INSERT_COLUMNS)
            sql_parts.append(
                f"INSERT INTO financial_reports ({col_list}) VALUES ({val_list});"
            )

    sql_parts.append("COMMIT;")

    if args.dry_run:
        print("Dry-run: в БД ничего не записано.")
    else:
        psql_exec("\n".join(sql_parts))
        print(f"Готово: создано {len(src_rows)} отчётов для {BANEP_TICKER}.")
        print(
            "История мультипликаторов: откройте карточку компании в UI "
            "(бэкфилл report_based выполнится автоматически) или "
            f"POST http://localhost:8000/companies/{banep_id}/multipliers/refresh"
        )


if __name__ == "__main__":
    main()
