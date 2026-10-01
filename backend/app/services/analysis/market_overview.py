"""Сводка о рынке: индексы, ставки и оценка рынка по годам.

Оценка рынка собирается из наших же мультипликаторов, а не берётся у
Мосбиржи: биржа P/E индекса не публикует, а наш свод тем ценен, что считан
тем же способом, что и карточка компании.

Две оговорки, которые страница обязана повторить:
  · **выжившие.** В базе только компании, которые торгуются сегодня. Те, что
    ушли с биржи или обанкротились, в прошлых годах отсутствуют, и прошлое
    рынка выглядит чуть лучше, чем было;
  · **проверенные.** Берутся только компании с проверенными отчётами и без
    дефектов аудита (`trustworthy_tickers`): одна ошибка в числе акций у
    крупной компании сдвинула бы P/E всего рынка.

P/E рынка — капитализация всех компаний, делённая на их прибыль вместе с
убыточными: так его считает индекс. Медианный P/E — середина по компаниям с
прибылью, на него не влияют гиганты.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.key_rate import KeyRate
from app.models.key_rate_daily import KeyRateDaily
from app.models.ofz_yield import OfzYield
from app.services.analysis.market_snapshot import trustworthy_tickers
from app.services.market.index_service import CODES, series
from app.services.market.ofz_service import OfzSeries, month_average

FIRST_YEAR = 2013


def _aggregate(rows) -> Optional[dict]:
    """rows: (cap, profit, equity, pe, dividend_yield) по компаниям."""
    cap_total = profit_total = equity_total = dy_weighted = cap_with_dy = 0.0
    pes = []
    count = 0
    for cap, profit, equity, pe, dy in rows:
        if cap is None or profit is None or float(cap) <= 0:
            continue
        cap, profit = float(cap), float(profit)
        count += 1
        cap_total += cap
        profit_total += profit
        if equity is not None and float(equity) > 0:
            equity_total += float(equity)
        if pe is not None and 0 < float(pe) < 200:
            pes.append(float(pe))
        if dy is not None:
            dy_weighted += float(dy) * cap
            cap_with_dy += cap
    if count == 0 or profit_total <= 0:
        return None
    return {
        "companies": count,
        "pe": round(cap_total / profit_total, 2),
        "pe_median": round(median(pes), 2) if pes else None,
        "earnings_yield": round(profit_total / cap_total * 100, 2),
        "pb": round(cap_total / equity_total, 2) if equity_total > 0 else None,
        "dividend_yield": round(dy_weighted / cap_with_dy, 2) if cap_with_dy > 0 else None,
        "cap_trln": round(cap_total / 1_000_000, 2),
    }


def valuation_by_year(db: Session) -> list[dict]:
    tickers = trustworthy_tickers(db)
    rows = db.execute(text(
        "select extract(year from m.date)::int as y, m.market_cap, m.ltm_net_income, m.equity, "
        "m.pe_ratio, m.dividend_yield "
        "from multipliers m join companies c on c.id = m.company_id "
        "where m.type = 'report_based' and c.ticker = any(:t) "
        "and extract(month from m.date) = 12"
    ), {"t": tickers}).fetchall()
    by_year: dict[int, list] = {}
    for y, *values in rows:
        by_year.setdefault(int(y), []).append(values)

    ofz = OfzSeries.load(db)
    key_rates = {row.year: float(row.avg_rate) for row in db.query(KeyRate)}

    out = []
    for year in sorted(by_year):
        if year < FIRST_YEAR:
            continue
        agg = _aggregate(by_year[year])
        if agg is None:
            continue
        ofz_avg = ofz.year_average(year)
        agg.update({
            "year": year,
            "ofz10": ofz_avg,
            "key_rate": key_rates.get(year),
            # Премия акций к облигациям по Грэму: доходность прибыли рынка
            # минус доходность длинного госдолга. Ниже нуля — облигация платит
            # больше, чем акции зарабатывают на рубль цены.
            "premium": round(agg["earnings_yield"] - ofz_avg, 2) if ofz_avg is not None else None,
        })
        out.append(agg)

    current_rows = db.execute(text(
        "select distinct on (m.company_id) m.market_cap, m.ltm_net_income, m.equity, "
        "m.pe_ratio, m.dividend_yield "
        "from multipliers m join companies c on c.id = m.company_id "
        "where m.type = 'current' and c.ticker = any(:t) "
        "order by m.company_id, m.date desc"
    ), {"t": tickers}).fetchall()
    now = _aggregate(current_rows)
    if now is not None:
        live = month_average(db)
        latest_key = db.query(KeyRateDaily).order_by(KeyRateDaily.date.desc()).first()
        ofz_now = live.value if live else None
        now.update({
            "year": "now",
            "ofz10": ofz_now,
            "key_rate": float(latest_key.rate) if latest_key else None,
            "premium": round(now["earnings_yield"] - ofz_now, 2) if ofz_now is not None else None,
        })
        out.append(now)
    return out


def _pairs(rows, attr="close") -> list:
    return [[r.date.isoformat(), float(getattr(r, attr))] for r in rows if getattr(r, attr) is not None]


def _change(rows, days: int) -> Optional[float]:
    if not rows:
        return None
    last = rows[-1]
    edge = last.date - timedelta(days=days)
    before = next((r for r in reversed(rows) if r.date <= edge), None)
    if before is None or float(before.close) <= 0:
        return None
    return round((float(last.close) / float(before.close) - 1) * 100, 2)


def key_rate_steps(db: Session) -> list:
    """Ключевая ставка ступеньками: только дни, когда она менялась."""
    out, prev = [], None
    for row in db.query(KeyRateDaily).order_by(KeyRateDaily.date):
        value = float(row.rate)
        if value != prev:
            out.append([row.date.isoformat(), value])
            prev = value
    last = db.query(KeyRateDaily).order_by(KeyRateDaily.date.desc()).first()
    if last is not None and out and out[-1][0] != last.date.isoformat():
        out.append([last.date.isoformat(), float(last.rate)])
    return out


def overview(db: Session) -> dict:
    indices = {code: series(db, code) for code in CODES}
    today = {}
    for code, rows in indices.items():
        if not rows:
            continue
        last = rows[-1]
        today[code] = {
            "date": last.date.isoformat(),
            "value": float(last.close),
            "day": _change(rows, 1),
            "year": _change(rows, 365),
            "yield": float(last.yield_pct) if last.yield_pct is not None else None,
            "duration_days": last.duration_days,
        }
    live = month_average(db)
    ofz_rows = db.query(OfzYield).order_by(OfzYield.date).all()
    latest_key = db.query(KeyRateDaily).order_by(KeyRateDaily.date.desc()).first()
    return {
        "today": today,
        "ofz10": {
            "month_average": live.value if live else None,
            "note": live.label if live else None,
            "last": float(ofz_rows[-1].y10) if ofz_rows else None,
            "last_date": ofz_rows[-1].date.isoformat() if ofz_rows else None,
        },
        "key_rate": {
            "value": float(latest_key.rate) if latest_key else None,
            "date": latest_key.date.isoformat() if latest_key else None,
        },
        "series": {
            "IMOEX": _pairs(indices.get("IMOEX", [])),
            "MCFTR": _pairs(indices.get("MCFTR", [])),
            "RGBI": _pairs(indices.get("RGBI", [])),
            "RGBI_yield": _pairs(indices.get("RGBI", []), "yield_pct"),
            "ofz10": [[r.date.isoformat(), float(r.y10)] for r in ofz_rows],
            "key_rate": key_rate_steps(db),
        },
        "valuation": valuation_by_year(db),
        "as_of": date.today().isoformat(),
    }
