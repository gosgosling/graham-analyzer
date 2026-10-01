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
from datetime import date as date_type
from typing import Optional

from app.utils.per_share import per_share
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

# Окна, на которые сжимается нормализация при короткой истории. Те же, что
# считает `earning_power`; три — нижний предел: у Грэма это окно вопроса
# «дорого ли сейчас» (гл. 14, P/E к средней прибыли за три года).
SHORT_WINDOWS = (5, 3)


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
            "price": per_share(self.price),
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


def year_models(
    db,
    company,
    window: int = DEFAULT_WINDOW,
    basis: str = "trend",
    points: Optional[list] = None,
) -> list:
    """Данные каждого года, из которых собирается оценка. → [(год, цена, оценить)].

    Разделено надвое, потому что стоимость у частей разная. Подготовить год —
    дорого: обрезать ряд, нормализовать прибыль, посчитать ровность и выплату.
    Получить полосу при заданной ставке — дёшево. Гейту нужна одна ставка на
    год, графику — своя на каждое решение ЦБ, а у ЛУКОЙЛа их за 2015 год
    восемь. Готовить год восемь раз ради восьми ставок незачем.

    `оценить(ставка_ключевая, премия, потолок_роста, risk_free=…)` возвращает
    полосу. Ключевая нужна проверке достоверности процентов; безрисковая —
    фактическая доходность ОФЗ, а без неё — ключевая плюс надбавка.
    """
    from app.models.financial_report import FinancialReport

    if points is None:
        points = load_points(db, company.id)
    if not points:
        return []

    is_lender = str(getattr(company, "company_type", "")).upper().endswith("LENDER")
    reports = {
        report.fiscal_year: report
        for report in db.query(FinancialReport).filter(
            FinancialReport.company_id == company.id,
            FinancialReport.period_type == "ANNUAL",
        )
    }

    models = []
    for point in sorted(points, key=lambda p: p.year):
        year = point.year
        price = point.price_normalized
        if not price:
            continue

        # Единственная защита от заглядывания вперёд, зато полная: за пределы
        # этого среза расчёт не видит ничего — ни будущей прибыли, ни выросшей
        # балансовой стоимости.
        history = [p for p in points if p.year <= year]
        # Окно сжимается под историю, а не отменяет год. У Сбера годовые
        # отчёты в базе начинаются с 2016-го, более ранних не найти, и при
        # строгих семи годах первая оценка выходила только по отчёту за
        # 2022-й — шесть лет графика пустовали. Короткое окно хуже длинного, и
        # за это платит надбавка за короткую историю внутри `value_band`; но
        # оценка по средней за три года лучше, чем никакой. Меньше трёх лет —
        # не ряд, а несколько точек, и оценки там нет.
        w = next((size for size in (window, *SHORT_WINDOWS) if len(history) >= size), None)
        if w is None:
            continue

        power = analyze(history, with_cash=not is_lender)
        steadiness = stability(history)
        dividends = payout_over_window(history, w)
        buyback = buyback_payout(history, w)
        payout = dividends
        if dividends is not None and buyback is not None:
            payout = round(dividends + buyback, 2)

        report = reports.get(year)

        def _num(field, _report=report):
            value = getattr(_report, field, None) if _report else None
            return None if value is None else float(value)

        ladders, observed = {}, {}
        for name, estimate in (
            (LADDER_EARNINGS, power.earnings.get(w)),
            (LADDER_CASH, power.cash.get(w)),
            (LADDER_OWNER, power.owner.get(w)),
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

        def evaluate(
            rate,
            risk_premium,
            growth_cap=None,
            *,
            risk_free=None,
            _num=_num, _power=power, _steady=steadiness, _payout=payout,
            _ladders=ladders, _observed=observed, _history=history, _w=w,
        ):
            verdict = structure(
                _num("operating_profit"),
                _num("finance_costs"),
                # Ровно те же слагаемые, что и в живом расчёте: лизинговые
                # проценты в знаменателе и проверка расходов по ставке того
                # момента — здесь ничего сегодняшнего быть не должно, включая
                # мерку достоверности.
                lease_interest=_num("lease_interest"),
                debt=_num("debt"),
                key_rate=rate,
            )
            return value_band(
                payout=_payout,
                roe=_steady.median if _steady else None,
                # Фактическая доходность длинных ОФЗ, когда она известна; без
                # неё — заменитель «ключевая + надбавка», который после шоков
                # завышает безрисковую на три пункта (см. `OfzYield`).
                risk_free_rate=(float(risk_free) if risk_free is not None
                                else float(rate) + OFZ_OVER_KEY_RATE),
                risk_premium=risk_premium,
                normal_earnings=_ladders,
                book_value_per_share=_power.book_value_per_share,
                structure=verdict,
                stability_label=_steady.label if _steady else None,
                history_years=len(_history),
                cash_backing=_power.backing.get(_w, {}).get("ratio"),
                growth_cap=growth_cap,
                basis=basis,
                # Оба параметра обязаны ехать сюда, иначе гейт проверяет не ту
                # модель, которую мы показываем: без `observed_growth` денежная
                # лестница получила бы нулевой рост, без `distortion` — не
                # получила бы надбавки за годы, где заработок подменён
                # начислениями.
                observed_growth=_observed,
                distortion=distortion_summary(_history, _w),
                # Рычаг того года, а не сегодняшний: заглядывать вперёд нельзя
                # и здесь.
                leverage=debt_to_equity(_num("debt"), _num("equity")),
            )

        models.append((year, float(price), evaluate))
    return models


def _row(year: int, price: float, band) -> "BacktestYear":
    return BacktestYear(
        year=year,
        price=price,
        low=None if band.refused else band.low,
        high=None if band.refused else band.high,
        conservative=None if band.refused else band.conservative,
        fair=None if band.refused else next(
            (item.value for item in band.ladders if item.name == LADDER_EARNINGS),
            band.high,
        ),
        method=None if band.refused else band.method,
        refused=band.reason if band.refused else None,
    )


def backtest(
    db,
    company,
    risk_premium: float,
    key_rates: dict,
    window: int = DEFAULT_WINDOW,
    growth_cap: Optional[float] = None,
    basis: str = "trend",
    risk_free_rates: Optional[dict] = None,
) -> BacktestResult:
    """Прогоняет оценку по всем годам, где хватает истории и известна ставка.

    `key_rates` — словарь «год → средняя ключевая ставка ЦБ, %».
    `risk_free_rates` — «год → средняя доходность 10-летних ОФЗ, %»; где она
    есть, безрисковая берётся из неё, а не из заменителя.
    """
    risk_free_rates = risk_free_rates or {}
    rows = []
    for year, price, evaluate in year_models(db, company, window, basis):
        rate = key_rates.get(year)
        if rate is None:
            continue
        band = evaluate(rate, risk_premium, growth_cap,
                        risk_free=risk_free_rates.get(year))
        rows.append(_row(year, price, band))
    return BacktestResult(ticker=str(company.ticker), years=rows)


def valuation_segments(
    db,
    company,
    risk_premium: float,
    rates,
    today_rate: float,
    today,
    lag,
    growth_cap: Optional[float] = None,
    window: int = DEFAULT_WINDOW,
    ofz=None,
    current_source: str = "допущения",
) -> list:
    """Оценка на каждый месяц истории — для графика.

    Ступень по отчёту за год Y начинается в день его раскрытия и держится до
    раскрытия следующего. Внутри неё оценка пересчитывается раз в месяц по
    средней ключевой ставке за двенадцать месяцев до этого дня — так, как её
    мог бы посчитать инвестор в тот момент.

    **Почему скользящая средняя, а не ставка дня и не средняя за год.**
    Проверено на всей базе: покупка в день раскрытия, цена через два года.

        средняя за год отчёта      опорная: ниже +10%, выше −9%, разрыв +19
        ставка на день раскрытия   опорная: ниже −4%,  выше −3%, разрыв −1
        средняя за 12 мес до дня   опорная: ниже +13%, выше −7%, разрыв +20

    Ставка конкретного дня сигнал разрушает: пики вроде апреля 2015-го или
    2022-го рынок смотрит насквозь. Средняя за год отчёта работает, но
    запаздывает: весь следующий год стоит в условиях прошлого. Скользящая
    средняя не хуже по сигналу, ничего не знает о будущем и обновляется
    каждый месяц.

    Для гейта это одно и то же: средняя за двенадцать месяцев на 31 декабря и
    есть средняя за год.

    `rates` — `RateSeries` с дневным рядом ключевой ставки, `ofz` —
    `OfzSeries` с доходностью 10-летних ОФЗ. Безрисковая берётся из ОФЗ на
    начало месяца; где кривой нет (до 2014 года), — скользящая ключевая плюс
    надбавка. `today_rate` — ключевая для отрезка, содержащего сегодняшний
    день: безрисковая там из допущений рынка, как и в карточке, иначе правый
    край графика расходился бы с ней.

    **Почему ОФЗ, а не ключевая.** Заменитель «ключевая за 12 месяцев + 1 п.п.»
    после шоков завышал безрисковую на три пункта: кривая переворачивается,
    ключевая выше длинных облигаций, потому что рынок ждёт её снижения. В июне
    2017 года он давал 11,0% при фактических 7,6%. При K − g в семь–девять
    пунктов лишние три срезали множитель почти на треть — отсюда «дорого» у
    трёх четвертей рынка в 2015–2019 годах.
    """
    from datetime import timedelta

    from app.services.analysis.earning_power import (
        graham_numbers, with_ltm,
    )

    from app.utils.disclosure import default_disclosure, disclosure_dates

    points = load_points(db, company.id)
    models = year_models(db, company, window, points=points)
    graham = graham_numbers(points)
    # Ступень встаёт в день фактического раскрытия отчёта, где он известен
    # (e-disclosure), и по правилу `lag` — где нет.
    disclosed = disclosure_dates(db, company.id)

    def annual_start(year):
        return disclosed.get((year, "ANNUAL"), date_type(year, 12, 31) + lag)

    steps = [
        (annual_start(year), year, evaluate, graham.get(year), None)
        for year, _price, evaluate in models
    ]

    # Ступени по последним двенадцати месяцам — для каждого года, где раскрыты
    # оба полугодия. Такая ступень встаёт в день раскрытия полугодия Y и
    # сменяет годовую ступень Y−1: отчёт, которому уже полгода, дальше не
    # держит оценку до весны, а уступает место свежим числам. Годовая ступень
    # Y, вышедшая следующей весной, сменяет её в свою очередь.
    #
    # Ряд для каждой такой ступени обрезается годом Y−1: LTM собирается из
    # отчётов, раскрытых к её дате, и из будущих лет не видит ничего.
    from app.models.financial_report import FinancialReport

    half_years = sorted({
        row[0] for row in db.query(FinancialReport.fiscal_year).filter(
            FinancialReport.company_id == company.id,
            FinancialReport.period_type == "SEMI_ANNUAL",
        )
    }) if points else []
    for year in half_years:
        # LTM собирается из годового отчёта Y−1 и двух полугодий: раньше, чем
        # раскрыты все три, ступени нет — иначе она знала бы годовой отчёт до
        # его публикации.
        start = max(
            disclosed.get((year, "SEMI_ANNUAL"), default_disclosure(year, "SEMI_ANNUAL")),
            annual_start(year - 1),
        )
        trimmed = [p for p in points if p.year <= year - 1]
        if start > today or not trimmed or trimmed[-1].year != year - 1:
            continue
        rolled = with_ltm(db, company.id, trimmed, start)
        if not rolled[-1].ltm_label:
            continue
        models_ltm = [m for m in year_models(db, company, window, points=rolled)
                      if m[0] == year - 1]
        if models_ltm:
            steps.append((start, year - 1, models_ltm[0][2],
                          graham_numbers(rolled).get(year - 1), rolled[-1].ltm_label))
    steps.sort(key=lambda item: item[0])

    def month_starts(start, end):
        cursor = date_type(start.year, start.month, 1)
        while True:
            cursor = (date_type(cursor.year + 1, 1, 1) if cursor.month == 12
                      else date_type(cursor.year, cursor.month + 1, 1))
            if cursor >= end:
                return
            yield cursor

    out = []
    for i, (start, year, evaluate, graham_value, ltm_label) in enumerate(steps):
        if start > today:
            continue  # отчёт ещё не раскрыт
        end = steps[i + 1][0] if i + 1 < len(steps) else today + timedelta(days=1)
        end = min(end, today + timedelta(days=1))

        bounds = [start, *month_starts(start, end), end]
        cache: dict = {}
        for seg_start, seg_end in zip(bounds, bounds[1:]):
            current = seg_start <= today < seg_end
            used = today_rate if current else rates.trailing(seg_start)
            if used is None:
                continue  # ставки ещё нет — до осени 2014 года средней не набирается
            risk_free = (used + OFZ_OVER_KEY_RATE) if current else (
                ofz.on(seg_start) if ofz else None)
            key = (round(used, 2), None if risk_free is None else round(risk_free, 2))
            if key not in cache:
                cache[key] = evaluate(used, risk_premium, growth_cap, risk_free=risk_free)
            row = _row(year, 0.0, cache[key])
            out.append({
                "from": seg_start.isoformat(),
                "till": seg_end.isoformat(),
                "year": year,
                "key_rate": round(used, 2),
                "risk_free": round(risk_free if risk_free is not None
                                   else used + OFZ_OVER_KEY_RATE, 2),
                "risk_free_source": (current_source if current else
                                     "ОФЗ 10 лет" if risk_free is not None
                                     else "ключевая + 1 п.п."),
                # Число Грэма от ставки не зависит и меняется только с отчётом.
                "graham": graham_value,
                "basis": ltm_label or f"отчёт {year}",
                "current": current,
                "fair": row.fair,
                "reference": row.conservative,
                "low": row.low,
                "high": row.high,
                "method": row.method,
                "refused": row.refused,
            })
    return out
