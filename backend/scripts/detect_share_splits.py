"""
Ищет дробления акций, сравнивая два ответа Мосбиржи об одной и той же сессии.

Списка корпоративных действий ISS не публикует, но выдаёт цену дважды и
по-разному:

* `/iss/history/…`   — как торговалось в тот день, без пересчёта;
* `/iss/…/candles`   — приведённое к сегодняшнему масштабу.

Их отношение на любую дату и есть накопленный коэффициент дроблений после
неё. У Т-Технологий на 30.12.2025 история даёт 3 277,6 ₽, свеча — 328 ₽,
отношение 10: ровно то самое дробление 10:1. Там, где сплитов не было,
отношение равно единице с точностью до копеечных расхождений.

Отсюда алгоритм: посчитать отношение в начале и в конце истории, и если они
разошлись — двоичным поиском найти день, когда это случилось. Восемь запросов
на сплит вместо перебора всей истории по дням.

    python -m scripts.detect_share_splits            # все компании
    python -m scripts.detect_share_splits T SBER     # выборочно
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Optional

import requests

from app.database import SessionLocal
from app.models.company import Company

_HISTORY = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares"
    "/securities/{ticker}.json"
)
_CANDLES = (
    "https://iss.moex.com/iss/engines/stock/markets/shares"
    "/securities/{ticker}/candles.json"
)

# Свечи и история берут закрытие немного по-разному (режимы торгов, аукцион
# закрытия), поэтому единицей считается всё, что рядом с ней.
_SAME = 0.05
# Круглые коэффициенты, которыми объявляют дробления и консолидации.
_ROUND_RATIOS = (2, 3, 4, 5, 10, 20, 40, 50, 100, 1000)


def _get(url: str, params: dict) -> Optional[dict]:
    for _ in range(3):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.RequestException, ValueError):
            continue
    return None


def _as_traded(ticker: str, since: date, till: date) -> dict[str, float]:
    data = _get(_HISTORY.format(ticker=ticker), {
        "from": since.isoformat(), "till": till.isoformat(),
        "limit": 100, "iss.meta": "off",
    })
    block = (data or {}).get("history", {})
    cols, rows = block.get("columns", []), block.get("data", [])
    if "TRADEDATE" not in cols:
        return {}
    i_d = cols.index("TRADEDATE")
    i_p = cols.index("LEGALCLOSEPRICE") if "LEGALCLOSEPRICE" in cols else cols.index("CLOSE")
    return {r[i_d]: float(r[i_p]) for r in rows if r[i_p]}


def _adjusted(ticker: str, since: date, till: date) -> dict[str, float]:
    data = _get(_CANDLES.format(ticker=ticker), {
        "from": since.isoformat(), "till": till.isoformat(),
        "interval": 24, "iss.meta": "off",
    })
    block = (data or {}).get("candles", {})
    cols, rows = block.get("columns", []), block.get("data", [])
    if "begin" not in cols or "close" not in cols:
        return {}
    i_b, i_c = cols.index("begin"), cols.index("close")
    return {r[i_b][:10]: float(r[i_c]) for r in rows if r[i_c]}


def _factor_near(ticker: str, when: date) -> Optional[float]:
    """Накопленный коэффициент дроблений после `when` — или None, если не торговалось."""
    since, till = when - timedelta(days=12), when + timedelta(days=12)
    traded, adjusted = _as_traded(ticker, since, till), _adjusted(ticker, since, till)
    common = sorted(set(traded) & set(adjusted))
    if not common:
        return None
    day = min(common, key=lambda d: abs((date.fromisoformat(d) - when).days))
    if not adjusted[day]:
        return None
    return traded[day] / adjusted[day]


def _trading_span(ticker: str) -> Optional[tuple[date, date]]:
    out = []
    for order in ("asc", "desc"):
        data = _get(_HISTORY.format(ticker=ticker), {
            "from": "1997-01-01", "limit": 1, "sort_order": order, "iss.meta": "off",
        })
        block = (data or {}).get("history", {})
        rows, cols = block.get("data", []), block.get("columns", [])
        if not rows or "TRADEDATE" not in cols:
            return None
        out.append(date.fromisoformat(rows[0][cols.index("TRADEDATE")]))
    return out[0], out[1]


def _same(a: float, b: float) -> bool:
    return abs(a / b - 1) <= _SAME if b else False


def _nearest_round(ratio: float) -> float:
    """Ближайший круглый коэффициент — объявляют их именно так."""
    best, err = ratio, float("inf")
    for candidate in _ROUND_RATIOS:
        for value in (float(candidate), 1.0 / candidate):
            delta = abs(ratio / value - 1)
            if delta < err:
                best, err = value, delta
    return best if err <= 0.08 else round(ratio, 3)


def _find_boundaries(ticker: str, lo: date, hi: date,
                     f_lo: float, f_hi: float, out: list[dict]) -> None:
    """Двоичный поиск дня, на котором коэффициент сменился."""
    if _same(f_lo, f_hi):
        return
    # Окно в полторы недели уже точно накрывает сплит — дальше двоичный поиск
    # бесполезен: проба берёт ближайшую общую сессию и может перескочить
    # границу. Последний шаг делает точный проход по дням.
    while (hi - lo).days > 10:
        mid = lo + (hi - lo) / 2
        f_mid = _factor_near(ticker, mid)
        if f_mid is None:
            # Бумага в эти дни не торговалась — сдвигаем пробу.
            mid = mid + timedelta(days=7)
            f_mid = _factor_near(ticker, mid)
            if f_mid is None:
                return
        if _same(f_mid, f_lo):
            lo, f_lo = mid, f_mid
        elif _same(f_mid, f_hi):
            hi, f_hi = mid, f_mid
        else:
            # Между пробами больше одного сплита — делим обе половины.
            _find_boundaries(ticker, lo, mid, f_lo, f_mid, out)
            _find_boundaries(ticker, mid, hi, f_mid, f_hi, out)
            return

    # Внутри окна сплит виден по цене напрямую: за одну сессию она падает
    # кратно. Берём самый крупный разрыв — он и есть день смены масштаба.
    traded = _as_traded(ticker, lo - timedelta(days=7), hi + timedelta(days=7))
    days = sorted(traded)
    jump_day, jump_ratio = None, 1.0
    for before, after in zip(days, days[1:]):
        if not traded[after]:
            continue
        ratio = traded[before] / traded[after]
        if abs(ratio - 1) > abs(jump_ratio - 1):
            jump_day, jump_ratio = after, ratio

    out.append({
        "date": jump_day or hi.isoformat(),
        "ratio": _nearest_round(jump_ratio if jump_day else f_lo / f_hi),
        "raw": round(jump_ratio if jump_day else f_lo / f_hi, 3),
    })


def detect(ticker: str) -> list[dict]:
    span = _trading_span(ticker)
    if not span:
        return []
    first, last = span
    f_first, f_last = _factor_near(ticker, first + timedelta(days=5)), _factor_near(ticker, last)
    if f_first is None or f_last is None:
        return []
    found: list[dict] = []
    _find_boundaries(ticker, first + timedelta(days=5), last, f_first, f_last, found)
    found.sort(key=lambda x: x["date"])
    return found


def main() -> int:
    wanted = [t.upper() for t in sys.argv[1:]]
    db = SessionLocal()
    try:
        query = db.query(Company).order_by(Company.ticker)
        if wanted:
            query = query.filter(Company.ticker.in_(wanted))
        companies = [(c.id, str(c.ticker)) for c in query.all()]
    finally:
        db.close()

    print(f"Проверяю компаний: {len(companies)}\n")
    total = 0
    for _, ticker in companies:
        for hit in detect(ticker):
            total += 1
            ratio = hit["ratio"]
            kind = f"дробление {ratio:g}:1" if ratio >= 1 else f"консолидация 1:{1/ratio:.0f}"
            print(f'{ticker:<7} {kind:<22} с {hit["date"]}   (замер {hit["raw"]})')
            print(f'        {{"date": "{hit["date"]}", "ratio": {ratio:g}}}')
    print(f"\nНайдено: {total}. Проверьте глазами — вносить в «Дробления» карточки компании.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
