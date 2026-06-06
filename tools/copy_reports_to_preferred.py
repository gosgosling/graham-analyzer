#!/usr/bin/env python3
"""
Копирует отчёты обыкновенного тикера → привилегированный: те же финансовые
показатели, отдельные price_per_share, shares_outstanding и dividends (MOEX).

Примеры:
  python3 tools/copy_reports_to_preferred.py --source BANE --target BANEP
  python3 tools/copy_reports_to_preferred.py --source TATN --target TATNP \\
      --shares-current 147508500 --shares-before-2014 147508500

  python3 tools/copy_reports_to_preferred.py --dry-run --source TATN --target TATNP \\
      --shares-current 147508500
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
    get_shares_outstanding,
)

PG_CONTAINER = "graham_postgres"
PG_USER = "graham_user"
PG_DB = "graham_analyzer"

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Копирование отчётов на префовый тикер")
    parser.add_argument("--source", required=True, help="Тикер обыкновенных (TATN, BANE)")
    parser.add_argument("--target", required=True, help="Тикер префов (TATNP, BANEP)")
    parser.add_argument(
        "--shares-current",
        type=int,
        required=True,
        help="Акции в обращении префов (с 2014 года и далее)",
    )
    parser.add_argument(
        "--shares-before-2014",
        type=int,
        default=None,
        help="Акции до 2014 (если отличаются; по умолчанию = --shares-current)",
    )
    parser.add_argument(
        "--historical-cutoff-year",
        type=int,
        default=2013,
        help="Годы <= этого значения получают shares-before-2014",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_ticker = args.source.strip().upper()
    target_ticker = args.target.strip().upper()
    shares_recent = args.shares_current
    shares_old = args.shares_before_2014 or shares_recent
    cutoff = args.historical_cutoff_year

    def shares_for_year(fy: int) -> int:
        return shares_old if fy <= cutoff else shares_recent

    companies = psql_json(
        f"SELECT json_build_object('id', id, 'ticker', ticker) "
        f"FROM companies WHERE ticker IN ('{source_ticker}', '{target_ticker}') "
        f"ORDER BY ticker;"
    )
    by_ticker = {c["ticker"]: int(c["id"]) for c in companies}
    if source_ticker not in by_ticker or target_ticker not in by_ticker:
        print(f"{source_ticker}/{target_ticker} не найдены в БД", file=sys.stderr)
        sys.exit(1)

    source_id = by_ticker[source_ticker]
    target_id = by_ticker[target_ticker]

    moex_pref = get_shares_outstanding(target_ticker)
    if moex_pref:
        print(f"MOEX ISSUESIZE {target_ticker}: {moex_pref['issuesize']:,}")

    cnt_row = psql_json(
        f"SELECT json_build_object('c', COUNT(*)::int) "
        f"FROM financial_reports WHERE company_id = {target_id};"
    )
    if cnt_row and cnt_row[0]["c"] > 0:
        print(f"У {target_ticker} уже {cnt_row[0]['c']} отчёт(ов). Прерывание.")
        sys.exit(1)

    src_rows = psql_json(
        f"SELECT row_to_json(r) FROM financial_reports r "
        f"WHERE company_id = {source_id} ORDER BY report_date;"
    )
    print(
        f"Копирование {len(src_rows)} отчётов: {source_ticker} (id={source_id}) "
        f"→ {target_ticker} (id={target_id})"
    )
    print(f"  Акции: до {cutoff} г. — {shares_old:,}; с {cutoff + 1} г. — {shares_recent:,}")

    sql_parts: list[str] = [
        "BEGIN;",
        f"UPDATE companies SET is_preferred_share = true WHERE id = {target_id};",
    ]

    for src in src_rows:
        fy = int(src["fiscal_year"])
        rd = date.fromisoformat(src["report_date"])
        price = moex_price(target_ticker, rd)
        dps, div_paid = moex_dividends(target_ticker, fy)
        shares = shares_for_year(fy)

        vals = {
            "company_id": target_id,
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
                f"Скопировано с {source_ticker}; цена и дивиденды — {target_ticker} (MOEX); "
                f"акции — {shares:,} шт."
            ),
        }

        print(
            f"  {fy}: shares={shares:,} price={price} "
            f"div={dps} paid={div_paid}"
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
        print(f"Готово: создано {len(src_rows)} отчётов для {target_ticker}.")
        print(
            f"История мультипликаторов: GET /companies/{target_id}/multipliers/history"
            f"?type=report_based или карточка компании в UI."
        )


if __name__ == "__main__":
    main()
