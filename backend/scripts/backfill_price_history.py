"""Полная история цен из MOEX ISS — для графика на карточке компании.

    python -m scripts.backfill_price_history           # проверенные компании
    python -m scripts.backfill_price_history --all     # все с отчётами
    python -m scripts.backfill_price_history LKOH      # выборочно

Обычный бэкфилл при старте сервера докачивает только последние дни: он идёт
от даты последней записи вперёд. История назад им не наберётся никогда —
поэтому для неё отдельный проход с `force_from`.

Точка отсчёта — дата самого раннего отчёта компании. Раньше неё цена графику
не нужна: сравнивать её будет не с чем.
"""

from __future__ import annotations

import sys
from datetime import date

from app.database import SessionLocal
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.services.analysis import market_snapshot
from app.services.market.price_history_service import backfill_company_prices

# Раньше этого года дневных свечей у ISS по большинству бумаг нет, а у тех, где
# есть, они относятся к другой экономике и графику только мешают.
FLOOR = date(2010, 1, 1)


def main() -> int:
    wanted = {a.upper() for a in sys.argv[1:] if not a.startswith("--")}
    every = "--all" in sys.argv

    db = SessionLocal()
    try:
        if wanted:
            tickers = sorted(wanted)
        elif every:
            tickers = [str(c.ticker) for c in db.query(Company).order_by(Company.ticker)]
        else:
            tickers = market_snapshot.trustworthy_tickers(db)

        total = 0
        for ticker in tickers:
            company = db.query(Company).filter(Company.ticker == ticker).first()
            if company is None:
                continue
            earliest = (
                db.query(FinancialReport.report_date)
                .filter(FinancialReport.company_id == company.id)
                .order_by(FinancialReport.report_date)
                .first()
            )
            if earliest is None or earliest[0] is None:
                print(f"{ticker:<8} отчётов нет — цены не нужны")
                continue

            start = max(earliest[0], FLOOR)
            added = backfill_company_prices(db, company, force_from=start)
            total += added
            print(f"{ticker:<8} с {start} — добавлено {added}")

        print(f"\nвсего добавлено точек: {total}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
