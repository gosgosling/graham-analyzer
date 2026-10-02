"""
В какой шкале цена: как торговалась или уже пересчитана на дробление.

Проект хранит цены **как торговались** (см. `share_splits`). Мосбиржа долго
так и отдавала историю, но не всегда: историю Т-Технологий после дробления
10:1 от 17.04.2026 она пересчитала задним числом — за 10.04.2026 сейчас
отдаёт 319,6 ₽, хотя торговалось 3 196 ₽. В базе оказалась смесь: мосбиржевые
дни в новой шкале, дни из T-Invest — в старой. График делил на 10 всё, что
до дробления, и мосбиржевые цены уезжали к 32 ₽, а T-Invest давал всплески.

Полагаться на то, что источник отдаёт, нельзя ни в ту, ни в другую сторону:
сегодня одна бумага пересчитана, другая нет, завтра пересчитают третью.
Поэтому шкала не предполагается, а **определяется по самим ценам**: за день
акция не дешевеет вдесятеро. Если на границе дробления цены «до» к ценам
«после» относятся как коэффициент дробления — ряд как торговался; если как
единица — ряд уже пересчитан, и цены до дробления надо умножить обратно.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from functools import lru_cache
from statistics import median
from typing import Any, Callable, Iterable, Optional

from app.services.share_splits import normalize_splits

logger = logging.getLogger(__name__)

RAW = "raw"            # как торговалось
ADJUSTED = "adjusted"  # пересчитано на дробление

# Насколько отношение может отойти от ожидаемого. Полтора раза: за день у
# бумаги бывает −30%, но не «в десять раз» и не «в восемь».
TOLERANCE = math.log(1.5)
# Сколько дней с каждой стороны смотреть. Торги вокруг дробления часто
# останавливают на неделю (у Т — с 11 по 16 апреля), окно должно её покрыть.
WINDOW = timedelta(days=45)
EDGE_POINTS = 10


def classify(observed: float, ratio: float) -> Optional[str]:
    """Отношение цен «до/после» → шкала. None — не похоже ни на то, ни на другое."""
    if observed <= 0 or ratio <= 0:
        return None
    if abs(math.log(observed / ratio)) < TOLERANCE:
        return RAW
    if abs(math.log(observed)) < TOLERANCE:
        return ADJUSTED
    return None


def scale_at_split(points: Iterable[tuple[date, float]], split_date: date, ratio: float,
                   after: Optional[Iterable[tuple[date, float]]] = None) -> Optional[str]:
    """
    Шкала ряда `points` у одного дробления.

    Цены «после» по умолчанию берутся из того же ряда; `after` — чтобы
    сравнить с чужими: у T-Invest до дробления три точки, а после — ни
    одной подряд, и сравнивать их есть с чем только у Мосбиржи.
    """
    pts = sorted(points)
    before = [p for d, p in pts if split_date - WINDOW <= d < split_date and p > 0]
    post_src = sorted(after) if after is not None else pts
    post = [p for d, p in post_src if split_date <= d <= split_date + WINDOW and p > 0]
    if not before or len(post) < 3:
        return None
    observed = median(before[-EDGE_POINTS:]) / median(post[:EDGE_POINTS])
    return classify(observed, ratio)


def to_traded(price: float, day: date, splits: Any, adjusted: Callable[[dict], Optional[bool]]) -> float:
    """Цену из источника — в цену как торговалась: обратно умножить на
    дробления после `day`, если источник их уже учёл."""
    for entry in normalize_splits(splits):
        if date.fromisoformat(entry["date"]) > day and adjusted(entry):
            price *= entry["ratio"]
    return price


# ── Мосбиржа ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=256)
def moex_adjusted(ticker: str, split_date: str, ratio: float) -> Optional[bool]:
    """Пересчитала ли Мосбиржа историю `ticker` на это дробление.

    Ответ кэшируется на время жизни процесса: пересчёт истории задним числом
    случается раз в жизни бумаги, а спрашивать приходится на каждый отчёт.
    """
    from app.utils.moex_client import get_price_history

    day = date.fromisoformat(split_date)
    try:
        points = list(get_price_history(ticker, day - WINDOW, day + WINDOW))
    except Exception as exc:  # noqa: BLE001 — внешний HTTP
        logger.warning("Шкала цен %s у дробления %s: Мосбиржа не ответила (%s)", ticker, split_date, exc)
        return None
    scale = scale_at_split(points, day, ratio)
    if scale is None:
        logger.warning("Шкала цен %s у дробления %s не определилась", ticker, split_date)
        return None
    return scale == ADJUSTED


def traded_close_on_or_before(ticker: str, target: date, splits: Any) -> Optional[dict]:
    """`get_closing_price_on_or_before`, но цена — как торговалась в тот день."""
    from app.utils.moex_client import get_closing_price_on_or_before

    info = get_closing_price_on_or_before(ticker, target)
    if not info or info.get("price") is None or not normalize_splits(splits):
        return info
    day = date.fromisoformat(str(info.get("date") or target)[:10])
    price = to_traded(float(info["price"]), day, splits,
                      lambda e: moex_adjusted(ticker, e["date"], float(e["ratio"])))
    if price != float(info["price"]):
        logger.info("Цена %s на %s: Мосбиржа отдала %.4f в новой шкале, как торговалась — %.4f",
                    ticker, day, float(info["price"]), price)
    return {**info, "price": price}


# ── Ремонт хранимой истории ─────────────────────────────────────────────────

def repair_rows(rows: list[tuple[date, float, str]], splits: Any) -> dict[int, float]:
    """
    Какие строки пересчитать и на что умножить. Ключ — индекс в `rows`.

    Каждый источник проверяется отдельно: у одной бумаги Мосбиржа может быть
    пересчитана, а T-Invest — нет. Дробления идут от позднего к раннему:
    после исправления позднего цены между дроблениями становятся «как
    торговались», и раннее проверяется уже на них.
    """
    prices = [float(p) for _, p, _ in rows]
    factors: dict[int, float] = {}
    sources = sorted({s for _, _, s in rows})
    for entry in sorted(normalize_splits(splits), key=lambda e: e["date"], reverse=True):
        split_day = date.fromisoformat(entry["date"])
        ratio = float(entry["ratio"])
        after = [(d, prices[i]) for i, (d, _, _) in enumerate(rows) if d >= split_day]
        for source in sources:
            own = [(d, prices[i]) for i, (d, _, s) in enumerate(rows) if s == source and d < split_day]
            if not own:
                continue
            scale = scale_at_split(own, split_day, ratio, after=after)
            if scale == ADJUSTED:
                for i, (d, _, s) in enumerate(rows):
                    if s == source and d < split_day:
                        prices[i] *= ratio
                        factors[i] = factors.get(i, 1.0) * ratio
            elif scale is None and any(split_day - d <= WINDOW for d, _ in own):
                logger.warning("Шкала %s у дробления %s не определилась — строки оставлены как есть",
                               source, entry["date"])
    return factors


def repair_company_prices(db: Any, company: Any, dry_run: bool = False) -> int:
    """Привести хранимые цены компании к шкале «как торговалось». Возвращает
    число исправленных строк. Повторный запуск ничего не меняет."""
    from app.models.stock_price import StockPrice
    from app.services.share_splits import company_splits

    splits = company_splits(db, company)
    if not splits:
        return 0
    stored = db.query(StockPrice).filter(StockPrice.company_id == company.id).order_by(StockPrice.date).all()
    factors = repair_rows([(r.date, float(r.price), r.source) for r in stored], splits)
    if not factors:
        return 0
    logger.info("Цены %s: %d строк были в шкале после дробления — возвращены к торговавшейся",
                company.ticker, len(factors))
    if not dry_run:
        for i, factor in factors.items():
            stored[i].price = float(stored[i].price) * factor
        db.commit()
    return len(factors)


def unexplained_jumps(rows: list[tuple[date, float]], splits: Any, limit: float = 3.0) -> list[tuple[date, float]]:
    """Дни, когда цена прыгнула больше чем в `limit` раз, а дробления в этот
    день нет: незаписанное дробление или смесь шкал. Для аудита."""
    split_days = [date.fromisoformat(e["date"]) for e in normalize_splits(splits)]
    pts = sorted(rows)
    jumps = []
    for (d0, p0), (d1, p1) in zip(pts, pts[1:]):
        if p0 <= 0 or p1 <= 0:
            continue
        change = p1 / p0
        if max(change, 1 / change) < limit:
            continue
        if any(d0 < s <= d1 for s in split_days):
            continue
        jumps.append((d1, round(change, 3)))
    return jumps
