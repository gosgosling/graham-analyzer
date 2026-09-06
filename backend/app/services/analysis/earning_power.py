"""Способность получать прибыль: уровень, направление и достоверность.

Величина, которую Коттл называет earning power, — это не прибыль последнего
года и не прогноз. Это то, что компания зарабатывает в нормальных условиях, и
считать её книга велит **двумя независимыми способами** (гл. 30, с. 563–566):

    способ A   средняя на акцию за окно лет
    способ B   средняя отдача на капитал × балансовая стоимость на акцию

Совпадение способов — признак, что ряд ровный. Расхождение — признак роста или
падения, и тогда средняя врёт направленно: занижает растущих, завышает
падающих (табл. 30.3, с. 570). Поэтому рядом с уровнем всегда стоит
направление, иначе число читается как приговор.

Пары считаются по трём величинам:

    прибыль            EPS                   ROE × BVPS
    деньги             FCF на акцию          (FCF / капитал) × BVPS
    прибыль владельца  ПВ на акцию           (ПВ / капитал) × BVPS

**Прибыль берётся отчётная, а не нормализованная.** «Анализ ценных бумаг»
настаивает на этом прямо: в многолетних средних единовременные статьи надо
оставлять как напечатано. Списания и разовые доходы — часть того, чем
компания на самом деле занималась, и очищать каждый год по отдельности
значит систематически льстить: аналитик вычитает плохое чаще, чем хорошее.
На длинном окне средняя сама всё поглотит. Поэтому здесь работает
`net_income_reported`, а нормализованный `net_income` остаётся для оценки
одного конкретного года.

**Прибыль владельца** (Баффет, письмо акционерам 1986):

    ПВ = отчётная прибыль + амортизация − поддерживающий капекс

Поддерживающий капекс в отчётности не выделяется, и мы берём капекс целиком —
то есть оценка получается заниженной для того, кто строит. Сам Баффет об этой
подмене предупреждал и говорил, что предпочитает быть приблизительно правым.
Смысл величины в том, что она стоит **между** прибылью и свободным потоком:
от прибыли отличается вычетом настоящих трат на основные средства, от FCF —
тем, что не дёргается вместе с оборотным капиталом.

Деньги здесь — не замена прибыли, а её проверка. Множитель из гл. 32 считается
по прибыли (`payout / (K − g)`, где payout — доля **прибыли**), и подставить
туда FCF нельзя, не сломав арифметику. Зато отношение средних, `средний FCF на
акцию ÷ средняя EPS`, показывает, насколько прибыль обеспечена деньгами, — и
на окне лет это куда крепче, чем то же отношение за один год.

Горизонт зависит от вопроса, а не от вкуса — у Грэма это три разных
инструмента, стоящих в тексте рядом:

    3 года    дорого ли сейчас          («Разумный инвестор», гл. 14, P/E ≤ 15)
    5 лет     промежуточное сглаживание
    7 лет     уровень для оценки        (гл. 11)
    10 лет    рост: два конца десятилетия, каждый сглажен тройкой (гл. 14)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

# Окна, за которые считаем. Каждое отвечает на свой вопрос — см. модульную
# строку документации.
WINDOWS = (3, 5, 7, 10)
# Тест роста защитного инвестора: десятилетие, концы сглажены тройками.
GROWTH_SPAN = 10
GROWTH_SMOOTH = 3
# Прирост «не менее трети за десять лет» из критериев гл. 14.
GROWTH_THRESHOLD = 1 / 3
# Ниже этой доли прибыль деньгами не обеспечена, и оценку по прибыли надо
# помечать как недостоверную. Величина — предмет суждения, не расчёта.
CASH_BACKING_WEAK = 0.6

# Границы ровности ряда. Опора — Winn-Dixie из гл. 9: коридор доходности
# капитала шириной в 20% от уровня авторы считают образцовым. Порог «ровно»
# поставлен с запасом от этого образца, «разбросано» — там, где коридор
# сравнивается с самим уровнем.
STABLE_SPREAD = 0.35
MODERATE_SPREAD = 0.80
# Меньше пяти лет — не ряд, а несколько точек: коридор по ним ничего не значит.
MIN_STABILITY_YEARS = 5

# Во сколько раз должно измениться число акций, чтобы шаг вообще
# рассматривался как дробление. Выкуп меняет счёт на проценты.
SPLIT_RATIO = 1.5
# Насколько при этом позволено сдвинуться капиталу. Дробление денег в компанию
# не приносит: акций становится больше, капитал остаётся прежним. Размещение
# двигает и то, и другое — у Позитива акции выросли в 2,74 раза вместе с
# капиталом в 2,37, и это размывание, а не дробление.
SPLIT_EQUITY_TOLERANCE = 1.5
# Насколько позволено сдвинуться капитализации. Дробление её не меняет вовсе:
# акций больше во столько же раз, во сколько дешевле каждая. За год цена
# ходит, но не втрое. Проверка сильнее сверки капитала — она ловит не только
# размещение, но и ошибку в данных: у Позитива за 2020 год записано 6,2 млрд
# акций при капитале 2,5 млрд, и приведение по такому числу раздуло дивиденд
# в 258 раз.
SPLIT_CAP_TOLERANCE = 3.0
# Выплата за окно выше этой доли означает не щедрость, а сломанный ряд.
MAX_SANE_PAYOUT = 300.0
# Насколько число акций может измениться за год, чтобы это ещё считалось
# выкупом или размещением. Магнит выкупил у нерезидентов 31% за год — это
# предел настоящего события. Изменение вдвое и больше означает дробление,
# которое мы не распознали, или ошибку ввода: у Позитива за 2020 год записано
# 6,2 млрд акций вместо 24 млн, и без границы это превращается в «выкуп»
# семнадцати тысяч процентов прибыли.
MAX_BUYBACK_STEP = 2.0


@dataclass(frozen=True)
class YearPoint:
    """Один год ряда. Все величины — в рублях, отдача — в процентах."""

    year: int
    eps: Optional[float] = None
    fcf_per_share: Optional[float] = None
    owner_earnings_per_share: Optional[float] = None
    roe: Optional[float] = None
    fcf_to_equity: Optional[float] = None
    owner_earnings_to_equity: Optional[float] = None
    book_value_per_share: Optional[float] = None
    dividends_per_share: Optional[float] = None
    # Число акций в масштабе последнего года: дробления приведены, выкуп нет.
    # Нужно, чтобы отличить возврат капитала выкупом от размывания эмиссией.
    shares_normalized: Optional[float] = None
    # Цена в том же масштабе — вместе с числом акций даёт стоимость выкупа.
    price_normalized: Optional[float] = None
    # Объявляла ли компания выплату за этот год. Отличает «не платит» от
    # «сумму не занесли»: без этого пустое поле читается как ноль и честно
    # платящая компания получает отказ в оценке.
    dividends_declared: Optional[bool] = None


@dataclass
class Average:
    """Средняя за окно — вместе с тем, из чего она сложилась.

    Полнота едет с величиной неразлучно: средняя за три года из окна в семь и
    средняя за семь лет — разные величины, и молча выдавать их одинаково
    нельзя.
    """

    value: float
    window: int
    years_used: int
    first_year: int
    last_year: int
    peak: float
    crosses_zero: bool

    @property
    def complete(self) -> bool:
        return self.years_used == self.window

    def as_dict(self) -> dict:
        return {
            "value": round(self.value, 4),
            "window": self.window,
            "years_used": self.years_used,
            "complete": self.complete,
            "first_year": self.first_year,
            "last_year": self.last_year,
            "peak": round(self.peak, 4),
            "crosses_zero": self.crosses_zero,
        }


@dataclass
class Estimate:
    """Способность получать прибыль, посчитанная двумя способами."""

    window: int
    per_share: Optional[Average] = None       # способ A
    average_return: Optional[Average] = None  # средняя отдача, %
    return_based: Optional[float] = None      # способ B = отдача × BVPS
    trend: Optional[Trend] = None             # уровень по тенденции, с. 568

    @property
    def divergence(self) -> Optional[float]:
        """Во сколько раз способы расходятся. Больше — ряд не ровный."""
        if self.per_share is None or self.return_based is None:
            return None
        a, b = self.per_share.value, self.return_based
        if a <= 0 or b <= 0:
            return None
        return round(max(a, b) / min(a, b), 3)

    def as_dict(self) -> dict:
        return {
            "window": self.window,
            "per_share": self.per_share.as_dict() if self.per_share else None,
            "average_return": self.average_return.as_dict() if self.average_return else None,
            "return_based": None if self.return_based is None else round(self.return_based, 4),
            "trend": self.trend.as_dict() if self.trend else None,
            "divergence": self.divergence,
        }


@dataclass
class Direction:
    """Куда движется ряд: средняя старшей половины против младшей."""

    older: float
    newer: float
    older_years: tuple
    newer_years: tuple

    @property
    def change(self) -> Optional[float]:
        """Прирост младшей половины к старшей, без округления.

        Округлять здесь нельзя: порог Грэма — ровно треть, и рост с 3,00 до
        4,00 обязан его проходить, а округлённые 0,3333 до 1/3 не дотягивают.
        Округление — забота отображения, и живёт в `as_dict`.
        """
        if self.older <= 0:
            return None
        return (self.newer - self.older) / self.older

    @property
    def label(self) -> str:
        change = self.change
        if change is None:
            return "не определено"
        if change >= 0.10:
            return "рост"
        if change <= -0.10:
            return "падение"
        return "ровно"

    def as_dict(self) -> dict:
        return {
            "older": round(self.older, 4),
            "newer": round(self.newer, 4),
            "older_years": list(self.older_years),
            "newer_years": list(self.newer_years),
            "change": None if self.change is None else round(self.change, 4),
            "label": self.label,
        }


def _points_by_year(points: Iterable[YearPoint]) -> dict:
    return {p.year: p for p in points}


def window_average(
    points: Iterable[YearPoint],
    attr: str,
    window: int,
    end_year: Optional[int] = None,
) -> Optional[Average]:
    """Средняя за `window` календарных лет, кончая `end_year`.

    Окно отсчитывается по календарю, а не по числу заполненных строк: если в
    середине не хватает года, средняя всё равно считается по тому, что есть,
    но `years_used` об этом скажет. Иначе дыра молча превратила бы
    пятилетнюю среднюю в четырёхлетнюю под тем же именем.
    """
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if getattr(p, attr) is not None]
    if not known:
        return None

    last = max(known) if end_year is None else end_year
    first = last - window + 1
    values = [
        (y, float(getattr(by_year[y], attr)))
        for y in range(first, last + 1)
        if y in by_year and getattr(by_year[y], attr) is not None
    ]
    if not values:
        return None

    numbers = [v for _, v in values]
    return Average(
        value=sum(numbers) / len(numbers),
        window=window,
        years_used=len(numbers),
        first_year=values[0][0],
        last_year=values[-1][0],
        peak=max(numbers),
        crosses_zero=min(numbers) < 0 < max(numbers),
    )


def latest_book_value(points: Iterable[YearPoint]) -> Optional[float]:
    """Балансовая стоимость последнего года — база для способа B."""
    known = [p for p in points if p.book_value_per_share is not None]
    if not known:
        return None
    return float(max(known, key=lambda p: p.year).book_value_per_share)


def estimate(
    points: Iterable[YearPoint],
    window: int,
    per_share_attr: str,
    return_attr: str,
    end_year: Optional[int] = None,
) -> Estimate:
    """Оба способа для одного окна.

    Способ B умножает среднюю отдачу на **текущую** балансовую стоимость —
    так у Коттла на примере McDonald's: 20,6% × 18,50 = 3,79 при средней EPS
    1,90. Смысл в том, чтобы учесть накопленный капитал, которого в старых
    годах ряда ещё не было.
    """
    points = list(points)
    per_share = window_average(points, per_share_attr, window, end_year)
    average_return = window_average(points, return_attr, window, end_year)
    book = latest_book_value(points)

    return_based = None
    if average_return is not None and book is not None:
        return_based = average_return.value / 100.0 * book

    return Estimate(
        window=window,
        per_share=per_share,
        average_return=average_return,
        return_based=return_based,
        trend=trend_value(points, per_share_attr, window, end_year),
    )


def capped_at_peak(value: Optional[float], average: Optional[Average]) -> Optional[float]:
    """Оценка не может быть выше уже достигнутого.

    Ограничение Коттла к оценке по тенденции (с. 568): пользоваться трендом
    можно, но «не использовать значения выше уже достигнутых». Тренд, уходящий
    за исторический максимум, — это уже прогноз, а не анализ.
    """
    if value is None or average is None:
        return value
    return min(value, average.peak)


def direction(
    points: Iterable[YearPoint],
    attr: str,
    window: int,
    end_year: Optional[int] = None,
) -> Optional[Direction]:
    """Направление ряда: средняя старшей половины против младшей.

    Нужно всегда, когда показывается средняя. Средняя занижает растущую
    компанию и завышает падающую, и без направления читатель не отличит
    одно от другого.
    """
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if getattr(p, attr) is not None]
    if not known:
        return None
    last = max(known) if end_year is None else end_year
    first = last - window + 1
    years = [y for y in range(first, last + 1)
             if y in by_year and getattr(by_year[y], attr) is not None]
    if len(years) < 4:
        return None

    half = len(years) // 2
    older_years, newer_years = years[:half], years[len(years) - half:]
    older = [float(getattr(by_year[y], attr)) for y in older_years]
    newer = [float(getattr(by_year[y], attr)) for y in newer_years]
    return Direction(
        older=sum(older) / len(older),
        newer=sum(newer) / len(newer),
        older_years=tuple(older_years),
        newer_years=tuple(newer_years),
    )


@dataclass
class Stability:
    """Насколько ровно держится величина. Мера из гл. 9, с. 144.

    Образец у авторов — Winn-Dixie: доходность капитала за пятнадцать лет ни
    разу не вышла из коридора 16,6–20,1%, а средние за две половины периода
    почти совпали (17,7 и 17,2). Отсюда две величины, а не одна: ширина
    коридора относительно уровня и расхождение половин. Первая ловит
    дёрганье, вторая — снос.

    Оговорка авторов остаётся в силе: ровная статистика не гарантирует ровного
    бизнеса. Texas Instruments рос 24% в год десять лет, потом ушёл в минус.
    """

    minimum: float
    maximum: float
    median: float
    years: int
    halves_gap: Optional[float] = None

    @property
    def relative_spread(self) -> Optional[float]:
        """Ширина коридора, делённая на уровень. У Winn-Dixie 0,20."""
        if not self.median or self.median <= 0:
            return None
        return round((self.maximum - self.minimum) / self.median, 3)

    @property
    def label(self) -> str:
        spread = self.relative_spread
        if spread is None:
            return "не определено"
        if spread <= STABLE_SPREAD:
            return "ровно"
        if spread <= MODERATE_SPREAD:
            return "умеренно"
        return "разбросано"

    def as_dict(self) -> dict:
        return {
            "minimum": round(self.minimum, 2),
            "maximum": round(self.maximum, 2),
            "median": round(self.median, 2),
            "years": self.years,
            "relative_spread": self.relative_spread,
            "halves_gap": self.halves_gap,
            "label": self.label,
        }


def stability(
    points: Iterable[YearPoint],
    attr: str = "roe",
    window: int = 10,
    end_year: Optional[int] = None,
) -> Optional[Stability]:
    """Коридор величины за окно и расхождение половин периода."""
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if getattr(p, attr) is not None]
    if not known:
        return None
    last = max(known) if end_year is None else end_year
    values = [
        float(getattr(by_year[y], attr))
        for y in range(last - window + 1, last + 1)
        if y in by_year and getattr(by_year[y], attr) is not None
    ]
    if len(values) < MIN_STABILITY_YEARS:
        return None

    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle] if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )

    gap = None
    half = len(values) // 2
    if half:
        older = sum(values[:half]) / half
        newer = sum(values[len(values) - half:]) / half
        if older > 0:
            gap = round((newer - older) / older, 3)

    return Stability(
        minimum=min(values),
        maximum=max(values),
        median=median,
        years=len(values),
        halves_gap=gap,
    )


def graham_growth(
    points: Iterable[YearPoint],
    attr: str = "eps",
    span: int = GROWTH_SPAN,
    smooth: int = GROWTH_SMOOTH,
    end_year: Optional[int] = None,
) -> Optional[Direction]:
    """Тест роста защитного инвестора: два конца десятилетия.

    Это то место, которое читается как «средняя за 10 лет и за 10 лет по
    предыдущий год». На деле скользящих средних нет: берутся первые три года
    десятилетия и последние три, каждая тройка усредняется, и сравниваются
    два сглаженных конца. Порог у Грэма — прирост не менее трети.
    """
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if getattr(p, attr) is not None]
    if not known:
        return None
    last = max(known) if end_year is None else end_year
    first = last - span + 1
    years = [y for y in range(first, last + 1)
             if y in by_year and getattr(by_year[y], attr) is not None]
    if len(years) < smooth * 2:
        return None

    older_years, newer_years = years[:smooth], years[-smooth:]
    older = [float(getattr(by_year[y], attr)) for y in older_years]
    newer = [float(getattr(by_year[y], attr)) for y in newer_years]
    return Direction(
        older=sum(older) / len(older),
        newer=sum(newer) / len(newer),
        older_years=tuple(older_years),
        newer_years=tuple(newer_years),
    )


def passes_graham_growth(growth: Optional[Direction]) -> Optional[bool]:
    if growth is None or growth.change is None:
        return None
    return growth.change >= GROWTH_THRESHOLD


@dataclass
class Trend:
    """Уровень по тенденции: то, чем пятое издание заменило простую среднюю.

    Авторы отказались от средней прямо (с. 568): «в прежних изданиях этой
    книги мы рекомендовали использовать для оценки будущей прибыли средние
    значения прошлой прибыли на акцию… при прогнозировании величины прибыли на
    акцию для типичной промышленной компании следует использовать тенденции
    развития». Причина в табл. 30.3: средняя занижает растущих и завышает
    падающих. Обратный тест подтвердил это на наших данных — у растущих
    компаний промахи вверх относятся к промахам вниз как 24 к 1.

    Линия проводится **методом наименьших квадратов**, а не по крайним точкам.
    Книга показывает, почему: темп роста промышленного индекса Value Line за
    1972–1981 по крайним точкам равен 11,5%, а за 1973–1982 — 4,8%, то есть
    сдвиг на один год меняет ответ вдвое. По регрессии те же периоды дают
    13,9% и 12,1% — величина держится.

    **Ограничение по достигнутому пику** — оговорка авторов там же: не
    использовать значения выше уже достигнутых. Линия, ушедшая за исторический
    максимум, — это прогноз, а не анализ прошлого.
    """

    value: float
    slope: float
    years_used: int
    first_year: int
    last_year: int
    peak: float
    capped: bool

    @property
    def annual_growth(self) -> Optional[float]:
        """Темп роста линии в процентах от её уровня."""
        if self.value <= 0:
            return None
        return round(self.slope / self.value * 100.0, 2)

    def as_dict(self) -> dict:
        return {
            "value": round(self.value, 4),
            "slope": round(self.slope, 4),
            "annual_growth": self.annual_growth,
            "years_used": self.years_used,
            "first_year": self.first_year,
            "last_year": self.last_year,
            "peak": round(self.peak, 4),
            "capped": self.capped,
        }


def trend_value(
    points: Iterable[YearPoint],
    attr: str,
    window: int,
    end_year: Optional[int] = None,
) -> Optional[Trend]:
    """Уровень величины по линии тренда на последний год окна.

    Меньше трёх точек линию не определяют: через две проходит ровно одна
    прямая, и тенденцией это называть нельзя.
    """
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if getattr(p, attr) is not None]
    if not known:
        return None
    last = max(known) if end_year is None else end_year
    series = [
        (y, float(getattr(by_year[y], attr)))
        for y in range(last - window + 1, last + 1)
        if y in by_year and getattr(by_year[y], attr) is not None
    ]
    if len(series) < 3:
        return None

    n = len(series)
    mean_year = sum(y for y, _ in series) / n
    mean_value = sum(v for _, v in series) / n
    variance = sum((y - mean_year) ** 2 for y, _ in series)
    if variance == 0:
        return None
    slope = sum((y - mean_year) * (v - mean_value) for y, v in series) / variance

    fitted = mean_value + slope * (series[-1][0] - mean_year)
    peak = max(v for _, v in series)

    return Trend(
        value=min(fitted, peak),
        slope=slope,
        years_used=n,
        first_year=series[0][0],
        last_year=series[-1][0],
        peak=peak,
        capped=fitted > peak,
    )


def payout_over_window(
    points: Iterable[YearPoint],
    window: int,
    end_year: Optional[int] = None,
) -> Optional[float]:
    """Доля прибыли, ушедшая на дивиденды за окно лет, %.

    Считается **суммой к сумме**, а не средней по годам. Причина та же, по
    которой нормализуется сама прибыль: выплата одного года ничего не значит.
    У ЛУКОЙЛа за 2025-й дивиденд относится к провалившейся прибыли как 505%,
    хотя за семь лет компания раздавала около половины. Первое число сломало
    бы множитель, второе его описывает.

    Убыточные годы из знаменателя не выбрасываются — они часть того, что
    компания заработала за период.

    Отсутствие суммы дивиденда и отказ платить — разные вещи. У ФосАгро в
    отчётах стоит отметка «выплаты были», а сумма не занесена; посчитать это
    нулём значило бы объявить исправного плательщика скрягой и отказать ему в
    оценке. В таком случае возвращается None — «неизвестно», а не «ноль».
    """
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if p.eps is not None]
    if not known:
        return None
    last = max(known) if end_year is None else end_year

    dividends = profit = 0.0
    seen = False
    amounts_known = False
    declared_without_amount = False
    for year in range(last - window + 1, last + 1):
        point = by_year.get(year)
        if point is None or point.eps is None:
            continue
        seen = True
        profit += float(point.eps)
        if point.dividends_per_share is not None:
            dividends += float(point.dividends_per_share)
            amounts_known = True
        elif point.dividends_declared:
            declared_without_amount = True

    if not seen or profit <= 0:
        return None
    if not amounts_known and declared_without_amount:
        return None

    payout = round(dividends / profit * 100.0, 2)
    if payout > MAX_SANE_PAYOUT:
        # Не щедрость, а сломанный ряд: столько лет подряд раздавать втрое
        # больше заработанного нельзя. Вернуть число значило бы пустить
        # ошибку данных дальше по расчёту под видом факта.
        return None
    return payout


def buyback_payout(
    points: Iterable[YearPoint],
    window: int,
    end_year: Optional[int] = None,
) -> Optional[float]:
    """Доля прибыли, вернувшаяся владельцу через выкуп акций, %.

    Модели Гордона безразлична форма возврата, ей важно, что деньги дошли до
    владельца. Выкуп доносит их двумя путями: продавшим — наличными,
    оставшимся — увеличением доли в той же прибыли. Экономически это дивиденд,
    просто розданный не всем сразу.

    Коттл этого не учитывает, и не по недосмотру: пятое издание вышло в
    1988-м, а выкупы стали массовыми в США после правила SEC 10b-18 (1982) и
    по-настоящему в девяностых. У Apple выплата дивидендами около 15%, а
    вместе с выкупом — под девяносто, и без второго слагаемого формула
    объявляет компанию скрягой.

    **Эмиссия входит с минусом.** Выпуск новых акций не возвращает капитал, а
    забирает его: прежний владелец стал владеть меньшей долей. Отрицательная
    величина здесь — не ошибка, а размывание.

    Дробления в счёт не идут: они меняют число акций, не трогая ничьей доли.
    Поэтому считается по приведённому ряду, где дробления уже сняты.
    """
    by_year = _points_by_year(points)
    known = [y for y, p in by_year.items() if p.eps is not None]
    if not known:
        return None
    last = max(known) if end_year is None else end_year

    spent = profit = 0.0
    measured = False
    previous = None
    for year in range(last - window, last + 1):
        point = by_year.get(year)
        if point is None:
            previous = None
            continue
        if point.eps is not None and year > last - window:
            profit += float(point.eps) * (point.shares_normalized or 0.0)
        if (previous is not None and point.shares_normalized and point.price_normalized
                and previous.shares_normalized and year > last - window):
            step = point.shares_normalized / previous.shares_normalized
            if step > MAX_BUYBACK_STEP or step < 1 / MAX_BUYBACK_STEP:
                # Ни выкуп, ни размещение так не выглядят. Что именно
                # произошло — нераспознанное дробление или ошибка ввода —
                # отсюда не видно, и считать по такому ряду нельзя.
                return None
            retired = previous.shares_normalized - point.shares_normalized
            spent += retired * point.price_normalized
            measured = True
        previous = point

    if not measured or profit <= 0:
        return None
    return round(spent / profit * 100.0, 2)


def cash_backing(
    points: Iterable[YearPoint],
    window: int,
    end_year: Optional[int] = None,
) -> Optional[dict]:
    """Средний FCF на акцию ÷ средняя EPS за то же окно.

    Проверка, а не оценка: показывает, какая доля бумажной прибыли доходит до
    денег. За один год это отношение скачет вместе с капексом, на окне лет —
    уже характеристика компании.

    Смысл теряется, когда средняя EPS не положительна: делить на убыток
    бессмысленно, и в этом случае возвращается None.
    """
    eps = window_average(points, "eps", window, end_year)
    fcf = window_average(points, "fcf_per_share", window, end_year)
    if eps is None or fcf is None or eps.value <= 0:
        return None
    ratio = fcf.value / eps.value
    return {
        "ratio": round(ratio, 3),
        "window": window,
        "years_used": min(eps.years_used, fcf.years_used),
        "complete": eps.complete and fcf.complete,
        "weak": ratio < CASH_BACKING_WEAK,
    }


@dataclass
class Analysis:
    """Полный разбор одной компании."""

    windows: tuple = WINDOWS
    earnings: dict = field(default_factory=dict)   # окно → Estimate
    cash: dict = field(default_factory=dict)       # окно → Estimate
    owner: dict = field(default_factory=dict)      # окно → Estimate
    eps_direction: dict = field(default_factory=dict)
    backing: dict = field(default_factory=dict)
    growth: Optional[Direction] = None
    growth_passes: Optional[bool] = None
    book_value_per_share: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "book_value_per_share": self.book_value_per_share,
            "earnings": {w: e.as_dict() for w, e in self.earnings.items()},
            "cash": {w: e.as_dict() for w, e in self.cash.items()},
            "owner": {w: e.as_dict() for w, e in self.owner.items()},
            "eps_direction": {w: d.as_dict() for w, d in self.eps_direction.items()},
            "cash_backing": self.backing,
            "graham_growth": self.growth.as_dict() if self.growth else None,
            "graham_growth_passes": self.growth_passes,
        }


def analyze(
    points: Iterable[YearPoint],
    windows: tuple = WINDOWS,
    with_cash: bool = True,
    end_year: Optional[int] = None,
) -> Analysis:
    """Разбор ряда по всем окнам.

    `with_cash=False` — для банков. Свободный поток у них не измеряет
    заработок: движение клиентских денег на порядок больше собственного, и
    даже очищенный `core_fcf` для оценки не годится.
    """
    points = list(points)
    result = Analysis(
        windows=windows,
        book_value_per_share=latest_book_value(points),
    )
    for window in windows:
        result.earnings[window] = estimate(points, window, "eps", "roe", end_year)
        direction_ = direction(points, "eps", window, end_year)
        if direction_ is not None:
            result.eps_direction[window] = direction_
        if with_cash:
            result.cash[window] = estimate(
                points, window, "fcf_per_share", "fcf_to_equity", end_year
            )
            result.owner[window] = estimate(
                points, window, "owner_earnings_per_share",
                "owner_earnings_to_equity", end_year,
            )
            backing = cash_backing(points, window, end_year)
            if backing is not None:
                result.backing[window] = backing

    result.growth = graham_growth(points, "eps", end_year=end_year)
    result.growth_passes = passes_graham_growth(result.growth)
    return result


# ── Загрузка ряда из базы ──────────────────────────────────────────────────


def load_points(db, company_id: int) -> list:
    """Ряд по годам: кэш мультипликаторов плюс отчётная прибыль из отчёта.

    Из кэша берутся число акций, капитал и свободный поток — там всё уже
    переведено в рубли, а акции те, что были в обращении на дату отчёта, без
    ретроспективной поправки на дробления («как торговалось тогда»).

    Прибыль читается из самого отчёта, и именно отчётная: нормализованная
    величина в кэше очищена от разовых статей, а для многолетних средних
    очищать нельзя. По той же причине отдача на капитал здесь пересчитывается
    от отчётной прибыли и с сохранённым `roe` не совпадает.
    """
    from app.models.financial_report import FinancialReport
    from app.models.multiplier import Multiplier
    # Та же арифметика перевода, что и во всём кэше: держать вторую копию
    # правила пересчёта валют — верный способ развести их со временем.
    from app.services.analysis.multiplier_service import _field_rub

    rows = (
        db.query(Multiplier, FinancialReport)
        .join(FinancialReport, Multiplier.report_id == FinancialReport.id)
        .filter(
            Multiplier.company_id == company_id,
            Multiplier.type == "report_based",
        )
        .order_by(Multiplier.date)
        .all()
    )

    factors = split_factors(
        [(m.date.year, m.shares_used, m.equity, m.market_cap) for m, _ in rows]
    )

    points = []
    for mult, report in rows:
        shares = None if mult.shares_used is None else float(mult.shares_used)
        equity = None if mult.equity is None else float(mult.equity)
        fcf = own_cash_flow(mult)

        profit = _field_rub(report, "net_income_reported")
        depreciation = _field_rub(report, "depreciation_amortization")
        capex = _field_rub(report, "capex")

        # Прибыль владельца требует всех трёх слагаемых: без амортизации это
        # просто прибыль, без капекса — она же с завышением.
        owner = None
        if None not in (profit, depreciation, capex):
            owner = profit + depreciation - capex

        # Дробления приводят ряд к текущему масштабу; отдача на капитал от
        # числа акций не зависит и приведения не требует.
        scale = factors.get(mult.date.year, 1.0)

        def per_share(value_mln, _scale=scale):
            base = _per_share(value_mln, shares)
            return None if base is None else round(base / _scale, 6)

        points.append(
            YearPoint(
                year=mult.date.year,
                eps=per_share(profit),
                fcf_per_share=per_share(fcf),
                owner_earnings_per_share=per_share(owner),
                roe=_to_equity(profit, equity),
                fcf_to_equity=_to_equity(fcf, equity),
                owner_earnings_to_equity=_to_equity(owner, equity),
                book_value_per_share=per_share(equity),
                dividends_per_share=(
                    None if mult.ltm_dividends_per_share is None
                    else round(float(mult.ltm_dividends_per_share) / scale, 6)
                ),
                dividends_declared=getattr(report, "dividends_paid", None),
                # Приведённые счёт и цена: их произведение — капитализация,
                # неизменная при дроблении, поэтому выкуп по ним считается
                # честно, а дробление в него не попадает.
                shares_normalized=None if shares is None else shares * scale,
                price_normalized=(
                    None if mult.price_used is None
                    else float(mult.price_used) / scale
                ),
            )
        )
    return points


def split_factors(rows: list) -> dict:
    """Во сколько раз надо уменьшить величины на акцию каждого года.

    Значения на акцию через дробление несопоставимы: у Норникеля прибыль на
    акцию за 2023 год равна 1 399 ₽, а за 2024-й — 8,7 ₽, и разница целиком в
    том, что акций стало в сто раз больше. Усреднять такой ряд бессмысленно, а
    множитель по такой средней даёт стоимость в двадцать раз выше цены.

    Ряд приводится к текущему числу акций — так же, как этого требует IAS 33
    от самой отчётности. Хранение остаётся «как торговалось тогда»: приведение
    живёт в расчёте и на графике, где сравнимость и нужна.

    **Отличить дробление от размещения одним счётом акций нельзя, и это не
    придирка.** Сегежа выпустила 28 млрд новых акций — счёт вырос втрое, но
    это размывание, настоящая потеря для прежнего владельца, и стирать его
    приведением значило бы соврать в его пользу. Признак дробления в том, что
    **денег в компанию не пришло**: акций больше, капитал прежний. У
    Норникеля при дроблении сто к одному капитал сдвинулся на 22%, у Позитива
    при размещении вырос в 2,37 раза вместе с акциями.

    Выкуп не приводится по той же причине: сокративший счёт акций честно
    поднял прибыль на каждую оставшуюся.

    Без данных о капитале приведение не делается. Промолчать безопаснее, чем
    угадать: не приведённый ряд виден глазом, а стёртое размывание — нет.

    `rows` — тройки (год, число акций, капитал). Возвращается словарь
    «год → множитель», на который надо **разделить** величину на акцию.
    """
    known = sorted(
        (
            year,
            float(shares),
            None if equity is None else float(equity),
            None if market_cap is None else float(market_cap),
        )
        for year, shares, equity, market_cap in rows
        if shares
    )
    if len(known) < 2:
        return {}

    # Идём с конца: накапливаем дробления, случившиеся после каждого года.
    factors = {}
    factor = 1.0
    for (year, shares, equity, cap), (_, later_shares, later_equity, later_cap) in zip(
        reversed(known[:-1]), reversed(known[1:])
    ):
        step = later_shares / shares
        big_step = step >= SPLIT_RATIO or step <= 1 / SPLIT_RATIO
        if big_step and _within(equity, later_equity, SPLIT_EQUITY_TOLERANCE) \
                and _within(cap, later_cap, SPLIT_CAP_TOLERANCE):
            factor *= step
        factors[year] = factor
    factors[known[-1][0]] = 1.0
    return {year: value for year, value in factors.items() if value != 1.0}


def _within(before: Optional[float], after: Optional[float], tolerance: float) -> bool:
    """Осталась ли величина примерно на месте, пока число акций менялось в разы.

    Отсутствие данных — не подтверждение. Промолчать и не приводить ряд
    безопаснее, чем привести его по недостающему основанию.
    """
    if not before or not after or before <= 0 or after <= 0:
        return False
    return 1 / tolerance <= after / before <= tolerance


def own_cash_flow(row) -> Optional[float]:
    """Свободный поток компании — без чужих денег.

    У биржи, банка и маркетплейса в валовом FCF сидят клиентские депозиты и
    обязательства перед продавцами. У Мосбиржи за 2022 год это 1 209 млрд
    против 179 млрд собственных: разница в семь раз, и она ничего не говорит
    о том, сколько компания заработала.

    Поэтому очищенный поток имеет приоритет всегда, когда он посчитан, а
    валовой остаётся для обычных компаний, у которых чужих денег нет.
    """
    core = getattr(row, "ltm_core_fcf", None)
    if core is not None:
        return float(core)
    gross = getattr(row, "ltm_fcf", None)
    return None if gross is None else float(gross)


def _per_share(value_mln: Optional[float], shares: Optional[float]) -> Optional[float]:
    """Величина в млн → рубли на акцию."""
    if value_mln is None or not shares:
        return None
    return float(value_mln) * 1_000_000 / shares


def _to_equity(value_mln: Optional[float], equity_mln: Optional[float]) -> Optional[float]:
    """Отдача на капитал в процентах."""
    if value_mln is None or not equity_mln:
        return None
    return float(value_mln) / float(equity_mln) * 100.0
