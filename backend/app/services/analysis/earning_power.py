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

        points.append(
            YearPoint(
                year=mult.date.year,
                eps=_per_share(profit, shares),
                fcf_per_share=_per_share(fcf, shares),
                owner_earnings_per_share=_per_share(owner, shares),
                roe=_to_equity(profit, equity),
                fcf_to_equity=_to_equity(fcf, equity),
                owner_earnings_to_equity=_to_equity(owner, equity),
                book_value_per_share=_per_share(equity, shares),
            )
        )
    return points


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
