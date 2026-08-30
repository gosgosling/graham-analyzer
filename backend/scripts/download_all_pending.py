"""
Массовое скачивание отчётов, найденных на e-disclosure, но отсутствующих на диске.

Запускается напрямую, а не через HTTP: 402 файла с паузой 10–20 секунд между
ними — это около двух часов, и любой разумный таймаут запроса короче.

    ./venv/bin/python -m scripts.download_all_pending           # все
    ./venv/bin/python -m scripts.download_all_pending SBER GAZP # выборочно

Прогресс пишется в stdout построчно, поэтому за ходом можно следить
`tail -f`. Уже скачанные файлы пропускаются самим загрузчиком, так что
повторный запуск после обрыва безопасен и продолжает с места остановки.
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict

from app.database import SessionLocal
from app.models.disclosure import DisclosurePeriod
from app.services.disclosure.parse_queue import download_periods

# Сеть до e-disclosure нестабильна: DNS периодически отваливается. Тикер
# целиком дешевле повторить, чем терять его из-за одной сорвавшейся резолвии.
RETRIES = 2


def main() -> int:
    wanted = {t.upper() for t in sys.argv[1:]}
    db = SessionLocal()
    try:
        query = db.query(DisclosurePeriod).filter(
            DisclosurePeriod.coverage_status == "available",
            DisclosurePeriod.file_url.isnot(None),
        )
        if wanted:
            query = query.filter(DisclosurePeriod.ticker.in_(wanted))
        rows = query.order_by(DisclosurePeriod.ticker, DisclosurePeriod.fiscal_year).all()

        by_ticker: dict[str, list[int]] = defaultdict(list)
        for row in rows:
            by_ticker[str(row.ticker)].append(int(row.id))

        total = len(rows)
        print(f"К скачиванию: {total} файлов у {len(by_ticker)} компаний", flush=True)
        print("Пауза между файлами 10–20 сек — это требование площадки.\n", flush=True)

        ok = failed = 0
        started = time.time()
        for i, (ticker, ids) in enumerate(sorted(by_ticker.items()), 1):
            for attempt in range(1, RETRIES + 1):
                result = download_periods(db, ids)
                got = result["downloaded"]
                errs = result["errors"]
                if got or not errs:
                    break
                if attempt < RETRIES:
                    print(f"  {ticker}: повтор {attempt}/{RETRIES}", flush=True)
                    time.sleep(5)

            ok += got
            failed += len(errs)
            done = time.time() - started
            print(
                f"[{i}/{len(by_ticker)}] {ticker:<8} +{got}/{len(ids)}"
                f"   всего {ok}, ошибок {failed}, прошло {done/60:.0f} мин",
                flush=True,
            )
            for e in errs[:2]:
                print(f"     ! {e[:160]}", flush=True)

        print(f"\nГотово: скачано {ok}, ошибок {failed}, за {(time.time()-started)/60:.0f} мин",
              flush=True)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
