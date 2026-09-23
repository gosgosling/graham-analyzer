"""Проверка модели на истории: пересекала ли оценка цену за полный цикл.

Коттл, гл. 4, с. 53: «оценка компании, которая в ходе полного рыночного цикла
ни разу не совпадает с собственной ценой, автоматически возбуждает
подозрения». Это не отчётность, а **гейт**: пока он не пройден, показывать
полосу нельзя — не потому, что рынок прав, а потому, что модель, никогда не
попадающая в цену, не измеряет ничего.

**Заглядывание вперёд запрещено.** За каждый год оценка считается только по
тому, что было известно тогда: ряд обрезается по этот год включительно, и
балансовая стоимость берётся тогдашняя, а не сегодняшняя. Иначе тест
показывал бы, что модель хорошо объясняет прошлое, зная будущее, — то есть
ничего не показывал бы.

**Ставка тоже своя на каждый год.** Множитель почти целиком определяется
разностью `K − g`, и подставлять сегодняшние 16% в 2020 год, когда ключевая
ставка была 5%, значит объявить рынок тех лет безумным. Доходности длинных
ОФЗ по годам у нас нет, поэтому берётся ключевая ставка ЦБ плюс постоянная
надбавка — на сегодня разрыв между ними около пункта. Замена грубая, и она
названа здесь, а не спрятана.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.analysis.company_valuation import (
    DEFAULT_WINDOW,
    debt_to_equity,
    LADDER_CASH,
    LADDER_EARNINGS,
    LADDER_OWNER,
    value_band,
)
from app.services.analysis.earning_power import (
    analyze,
    buyback_payout,
    distortion_summary,
    load_points,
    payout_over_window,
    stability,
)
from app.services.analysis.valuation_guards import structure

# Насколько доходность длинных ОФЗ отличается от ключевой ставки. На
# 30.08.2026 ключевая 14,98% против ОФЗ 15,7–16,2% — около пункта. Величина
# ходит вместе с формой кривой, и постоянной её считать неточно; но иметь
# грубую ставку по каждому году лучше, чем одну сегодняшнюю на все.
OFZ_OVER_KEY_RATE = 1.0

# Минимум лет, на которых тест что-то значит. У Грэма полный рыночный цикл
# после 1926 года удлинился примерно до десяти лет; на пяти можно попасть в
# одну фазу и принять её за правило.
MIN_BACKTEST_YEARS = 5


@dataclass
class BacktestYear:
    """Оценка за один год против тогдашней цены."""

    year: int
    price: float
    low: Optional[float] = None
    high: Optional[float] = None
    # Опорная цена — та, от которой считается запас прочности. Для гейта она
    # не нужна (он смотрит на попадание полосы в цену), но ряд по годам без
    # неё неполон: именно её читатель сравнивает с ценой на графике.
    conservative: Optional[float] = None
    # Оценка по лестнице прибыли при рыночной премии. Отличается от `high`:
    # верх полосы берётся максимумом по всем трём лестницам, и у компании с
    # сильным денежным потоком это денежная ступень, вдвое выше прибыльной.
    # Карточка показывает именно прибыльную — та сопоставима с купоном
    # облигации, — и ряд на графике обязан показывать ту же величину, иначе
    # на одном экране выходят два разных числа под одним именем.
    fair: Optional[float] = None
    method: Optional[str] = None
    refused: Optional[str] = None

    @property
    def inside(self) -> Optional[bool]:
        if self.low is None or self.high is None:
            return None
        return self.low <= self.price <= self.high

    @property
    def distance(self) -> Optional[float]:
        """Во сколько раз цена отличается от ближайшей границы. Внутри — 1,0."""
        if self.low is None or self.high is None or self.price <= 0:
            return None
        if self.price < self.low:
            return round(self.low / self.price, 3)
        if self.price > self.high:
            return round(self.price / self.high, 3)
        return 1.0

    def as_dict(self) -> dict:
        return {
            "year": self.year,
            "price": round(self.price, 2),
            "low": self.low,
            "high": self.high,
            "conservative": self.conservative,
            "fair": self.fair,
            "method": self.method,
            "inside": self.inside,
            "distance": self.distance,
            "refused": self.refused,
        }


@dataclass
class BacktestResult:
    ticker: str
    years: list

    @property
    def counted(self) -> list:
        return [y for y in self.years if y.inside is not None]

    @property
    def hits(self) -> int:
        return sum(1 for y in self.counted if y.inside)

    @property
    def hit_rate(self) -> Optional[float]:
        if not self.counted:
            return None
        return round(self.hits / len(self.counted), 3)

    @property
    def median_distance(self) -> Optional[float]:
        values = sorted(y.distance for y in self.counted if y.distance is not None)
        if not values:
            return None
        middle = len(values) // 2
        return (values[middle] if len(values) % 2
                else round((values[middle - 1] + values[middle]) / 2, 3))

    @property
    def verdict(self) -> str:
        """Приговор модели по этой компании, а не компании по модели."""
        if len(self.counted) < MIN_BACKTEST_YEARS:
            return "мало лет"
        if self.hits == 0:
            return "ни разу"          # тот самый случай из гл. 4
        if self.hit_rate is not None and self.hit_rate >= 0.5:
            return "часто"
        return "изредка"

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "years": [y.as_dict() for y in self.years],
            "counted": len(self.counted),
            "hits": self.hits,
            "hit_rate": self.hit_rate,
            "median_distance": self.median_distance,
            "verdict": self.verdict,
        }


def backtest(
    db,
    company,
    risk_premium: float,
    key_rates: dict,
    window: int = DEFAULT_WINDOW,
    growth_cap: Optional[float] = None,
    basis: str = "trend",
) -> BacktestResult:
    """Прогоняет оценку по всем годам, где хватает истории и известна ставка.

    `key_rates` — словарь «год → средняя ключевая ставка ЦБ, %».
    """
    from app.models.financial_report import FinancialReport

    points = load_points(db, company.id)
    ticker = str(company.ticker)
    if not points:
        return BacktestResult(ticker=ticker, years=[])

    is_lender = str(getattr(company, "company_type", "")).upper().endswith("LENDER")
    reports = {
        report.fiscal_year: report
        for report in db.query(FinancialReport).filter(
            FinancialReport.company_id == company.id,
            FinancialReport.period_type == "ANNUAL",
        )
    }

    rows = []
    for point in sorted(points, key=lambda p: p.year):
        year = point.year
        price = point.price_normalized
        rate = key_rates.get(year)
        if not price or rate is None:
            continue

        # Единственная защита от заглядывания вперёд, зато полная: за пределы
        # этого среза расчёт не видит ничего — ни будущей прибыли, ни выросшей
        # балансовой стоимости.
        history = [p for p in points if p.year <= year]
        if len(history) < window:
            continue

        power = analyze(history, with_cash=not is_lender)
        steadiness = stability(history)
        dividends = payout_over_window(history, window)
        buyback = buyback_payout(history, window)
        payout = dividends
        if dividends is not None and buyback is not None:
            payout = round(dividends + buyback, 2)

        report = reports.get(year)

        def _num(field, _report=report):
            value = getattr(_report, field, None) if _report else None
            return None if value is None else float(value)

        verdict = structure(
            _num("operating_profit"),
            _num("finance_costs"),
            # Ровно те же слагаемые, что и в живом расчёте: лизинговые
            # проценты в знаменателе и проверка расходов по ставке того года.
            # Ставка берётся тогдашняя — здесь ничего сегодняшнего быть не
            # должно, включая мерку достоверности.
            lease_interest=_num("lease_interest"),
            debt=_num("debt"),
            key_rate=rate,
        )

        ladders, observed = {}, {}
        for name, estimate in (
            (LADDER_EARNINGS, power.earnings.get(window)),
            (LADDER_CASH, power.cash.get(window)),
            (LADDER_OWNER, power.owner.get(window)),
        ):
            if estimate is None or estimate.per_share is None:
                continue
            if basis == "trend" and estimate.trend is not None:
                ladders[name] = estimate.trend.value
            else:
                ladders[name] = estimate.per_share.value
            # Наблюдаемый рост денежной лестницы. Считается по обрезанному
            # ряду, как и всё остальное здесь: наклон, известный на тот год, а
            # не сегодняшний.
            if estimate.trend is not None:
                observed[name] = estimate.trend.annual_growth

        band = value_band(
            payout=payout,
            roe=steadiness.median if steadiness else None,
            risk_free_rate=float(rate) + OFZ_OVER_KEY_RATE,
            risk_premium=risk_premium,
            normal_earnings=ladders,
            book_value_per_share=power.book_value_per_share,
            structure=verdict,
            stability_label=steadiness.label if steadiness else None,
            history_years=len(history),
            cash_backing=power.backing.get(window, {}).get("ratio"),
            growth_cap=growth_cap,
            basis=basis,
            # Оба параметра обязаны ехать сюда, иначе гейт проверяет не ту
            # модель, которую мы показываем: без `observed_growth` денежная
            # лестница получила бы нулевой рост, без `distortion` — не получила
            # бы надбавки за годы, где заработок подменён начислениями.
            observed_growth=observed,
            distortion=distortion_summary(history, window),
            # Рычаг того года, а не сегодняшний: заглядывать вперёд нельзя и
            # здесь.
            leverage=debt_to_equity(_num("debt"), _num("equity")),
        )

        rows.append(BacktestYear(
            year=year,
            price=float(price),
            low=None if band.refused else band.low,
            high=None if band.refused else band.high,
            conservative=None if band.refused else band.conservative,
            fair=None if band.refused else next(
                (item.value for item in band.ladders if item.name == LADDER_EARNINGS),
                band.high,
            ),
            method=None if band.refused else band.method,
            refused=band.reason if band.refused else None,
        ))

    return BacktestResult(ticker=ticker, years=rows)
