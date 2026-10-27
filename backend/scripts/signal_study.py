"""
Проверка сигнала «дешевле опорной» на истории базы.

Для каждой проверенной компании и каждого месяца берётся опорная, которую сайт
показал бы в первый день месяца (`company_valuation_history`: только отчёты,
раскрытые к этой дате, и ставка, известная тогда), и цена через 12 месяцев.
Наблюдения группируются по запасу прочности и по тому, сколько месяцев подряд
бумага уже дешевле опорной на треть.

Ограничения, которые результат несёт с собой и показывает на сайте:
- доходность — по цене, без дивидендов (смещение против платящих компаний);
- выборка — сегодняшние проверенные компании, ушедшие с биржи не входят;
- компании с дроблениями пропускаются: цена в базе — как торговалась;
- правила модели нынешние и применены к прошлому.

Результат пишется в `app/data/signal_study.json`; его отдаёт
`/valuation/signal-study`, а карточка берёт оттуда число для подписи
«дешевле опорной уже N месяцев подряд».

    python -m scripts.signal_study
"""
from __future__ import annotations

import bisect
import json
import statistics
from collections import defaultdict
from datetime import date, timedelta
from itertools import groupby
from pathlib import Path

from sqlalchemy import text

from app.database import SessionLocal
from app.models.company import Company
from app.routers.valuation_router import company_valuation_history
from app.services.analysis.market_snapshot import trustworthy_tickers

OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "signal_study.json"
MARGIN = 1 / 3
HORIZON = timedelta(days=365)


def _group(name: str, key: str, rows: list) -> dict:
    returns = [r["ret"] for r in rows]
    return {
        "key": key,
        "name": name,
        "n": len(rows),
        "companies": len({r["ticker"] for r in rows}),
        "median": round(statistics.median(returns), 4) if returns else None,
        "share_up": round(sum(1 for x in returns if x > 0) / len(returns), 3) if returns else None,
    }


def main() -> int:
    db = SessionLocal()
    try:
        tickers = set(trustworthy_tickers(db))
        companies = [c for c in db.query(Company).order_by(Company.ticker)
                     if c.ticker in tickers and not c.share_splits]
        obs = []
        for company in companies:
            try:
                history = company_valuation_history(company_id=company.id, db=db)
            except Exception as exc:  # noqa: BLE001
                print(f"{company.ticker}: {exc}")
                continue
            prices = db.execute(text(
                "select date, price from stock_prices where company_id = :c order by date"
            ), {"c": company.id}).all()
            if not prices:
                continue
            days = [p[0] for p in prices]
            values = [float(p[1]) for p in prices]

            def price_on(day: date):
                i = bisect.bisect_left(days, day)
                if i >= len(days) or (days[i] - day).days > 10:
                    return None
                return values[i]

            for seg in history.get("segments", []):
                ref = seg.get("reference")
                start = date.fromisoformat(seg["from"])
                # Одна точка в месяц — его начало; ступень отчёта посреди
                # месяца здесь не нужна, она войдёт в следующий.
                if not ref or ref <= 0 or start.day > 5:
                    continue
                p0, p1 = price_on(start), price_on(start + HORIZON)
                if not p0 or not p1:
                    continue
                obs.append({"ticker": company.ticker, "day": start,
                            "margin": 1 - p0 / ref, "ret": p1 / p0 - 1})
    finally:
        db.close()

    streak = {}
    for ticker, group in groupby(sorted(obs, key=lambda o: (o["ticker"], o["day"])), key=lambda o: o["ticker"]):
        run = 0
        for o in group:
            run = run + 1 if o["margin"] >= MARGIN else 0
            streak[(ticker, o["day"])] = run
    for o in obs:
        o["streak"] = streak[(o["ticker"], o["day"])]

    cheap = [o for o in obs if o["margin"] >= MARGIN]
    by_year = defaultdict(list)
    for o in cheap:
        by_year[o["day"].year].append(o)

    result = {
        "generated": date.today().isoformat(),
        "period": [min(o["day"] for o in obs).isoformat(), max(o["day"] for o in obs).isoformat()],
        "observations": len(obs),
        "companies": len({o["ticker"] for o in obs}),
        "horizon_months": 12,
        "margin": round(MARGIN, 4),
        "by_margin": [
            _group("Все наблюдения", "all", obs),
            _group("Дороже опорной", "dear", [o for o in obs if o["margin"] < 0]),
            _group("Дешевле опорной меньше чем на треть", "thin", [o for o in obs if 0 <= o["margin"] < MARGIN]),
            _group("Дешевле опорной на треть и больше", "cheap", cheap),
        ],
        "by_streak": [
            _group("Дешёво впервые (1–3 мес. подряд)", "fresh", [o for o in cheap if o["streak"] <= 3]),
            _group("Дёшево 4–11 мес. подряд", "middle", [o for o in cheap if 4 <= o["streak"] <= 11]),
            _group("Дёшево уже 12 мес. и дольше", "long", [o for o in cheap if o["streak"] >= 12]),
        ],
        "by_year": [_group(str(year), str(year), rows) for year, rows in sorted(by_year.items())],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("generated", "period", "observations", "companies")}, ensure_ascii=False))
    for block in ("by_margin", "by_streak"):
        for g in result[block]:
            med = "—" if g["median"] is None else f"{g['median'] * 100:+.1f}%"
            print(f"  {g['name']:45s} n={g['n']:4d}  медиана {med}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
