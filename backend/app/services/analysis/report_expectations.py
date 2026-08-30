"""
Какие отчёты компания должна была сдать и каких у нас нет.

Отвечает не на вопрос «когда выйдет отчёт», а на более полезный — **что я
пропустил**. Разница принципиальная: точной даты будущей публикации не
существует в природе, потому что закон обязывает раскрыть отчётность не
позднее срока, но не обязывает объявлять день заранее. А вот «срок прошёл, а
отчёта у меня нет» — это факт, и он считается без единого внешнего запроса.

Три состояния на период:

    filed        отчёт внесён в базу
    window_open  период закончился, срок ещё не вышел
    overdue      срок вышел, отчёта нет — это и есть список дел

Закон здесь не моделируется намеренно. Обязанность раскрывать МСФО зависит от
организационной формы, уровня листинга и отрасли, а с 2022 года часть
эмитентов вправе ограничивать раскрытие. Вместо этого ожидание выводится из
поведения самой компании: сдавала полугодовые три года подряд — ждём и
теперь; никогда не сдавала квартальные — не ждём.

Срок тоже берётся из её собственной истории: медиана задержки «отчётная дата
→ публикация» по прошлым отчётам того же типа. Запасные значения — из
распределения по всей базе: у годовых видно два горба, 75–90 дней у тех, кто
торопится, и 105–119 у тех, кто тянет до предела.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Literal, Optional, Sequence

from app.models.enums import PeriodType

Status = Literal["filed", "window_open", "overdue"]

# Запасной срок, когда у компании нет своей истории публикаций, дней.
# Верхняя граница наблюдаемого распределения, а не «средний срок»: пока он не
# прошёл, называть отчёт просроченным нельзя.
DEFAULT_LAG_DAYS: Dict[str, int] = {
    PeriodType.ANNUAL.value: 120,
    PeriodType.SEMI_ANNUAL.value: 60,
    PeriodType.QUARTERLY.value: 60,
}

# Насколько отодвинуть собственную медиану компании, прежде чем считать отчёт
# просроченным. Медиана — середина: половина отчётов выходит позже неё, и без
# запаса половина компаний висела бы в «просрочено» каждый год.
LAG_MARGIN_DAYS = 30

# Сколько последних лет смотреть, решая, сдаёт ли компания промежуточные.
# Три года переживают одну пропущенную публикацию, но не дают ждать вечно
# того, что компания перестала делать.
INTERIM_LOOKBACK_YEARS = 3


def normalize_period_type(value: object) -> Optional[str]:
    """Тип периода к единому виду.

    SQLAlchemy хранит перечисление именем (`ANNUAL`), схемы и код оперируют
    значением (`annual`), а из сырого SQL приходит строка. Сравнивать их
    напрямую нельзя: раньше из-за этого ни один отчёт не находился в базе и
    все периоды числились пропущенными.
    """
    if value is None:
        return None
    raw = value.value if hasattr(value, "value") else str(value)
    lowered = raw.lower()
    for member in PeriodType:
        if lowered in (member.value.lower(), member.name.lower()):
            return member.value
    return lowered


@dataclass(frozen=True)
class ExpectedPeriod:
    """Один ожидаемый период со своим статусом."""

    period_type: str
    fiscal_year: int
    fiscal_quarter: Optional[int]
    period_key: str
    period_label: str
    period_end: date
    deadline: date
    status: Status
    report_id: Optional[int] = None
    days_overdue: Optional[int] = None


def period_end_date(period_type: str, year: int, quarter: Optional[int]) -> date:
    """Последний день отчётного периода."""
    if period_type == PeriodType.ANNUAL.value:
        return date(year, 12, 31)
    if period_type == PeriodType.SEMI_ANNUAL.value:
        return date(year, 6, 30)
    q = quarter or 1
    month_end = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}[q]
    return date(year, month_end[0], month_end[1])


def _label(period_type: str, year: int, quarter: Optional[int]) -> str:
    if period_type == PeriodType.ANNUAL.value:
        return f"{year} год"
    if period_type == PeriodType.SEMI_ANNUAL.value:
        return f"1П {year}"
    return f"{quarter} кв {year}"


def _key(period_type: str, year: int, quarter: Optional[int]) -> str:
    if period_type == PeriodType.ANNUAL.value:
        return str(year)
    if period_type == PeriodType.SEMI_ANNUAL.value:
        return f"{year}H1"
    return f"{year}Q{quarter}"


def median_lag_days(reports: Sequence[object], period_type: str) -> Optional[int]:
    """
    Медиана задержки «отчётная дата → публикация» по отчётам этого типа.

    Отрицательные лаги отбрасываются: публикация раньше отчётной даты
    физически невозможна и означает опечатку в годе при вводе.
    """
    lags: List[int] = []
    for rep in reports:
        if normalize_period_type(getattr(rep, "period_type", None)) != period_type:
            continue
        filed = getattr(rep, "filing_date", None)
        ends = getattr(rep, "report_date", None)
        if filed is None or ends is None:
            continue
        lag = (filed - ends).days
        if lag > 0:
            lags.append(lag)
    if not lags:
        return None
    return int(statistics.median(lags))


def deadline_for(
    reports: Sequence[object], period_type: str, period_end: date
) -> date:
    """Дата, после которой отсутствие отчёта считается пропуском."""
    own = median_lag_days(reports, period_type)
    if own is not None:
        lag = own + LAG_MARGIN_DAYS
    else:
        lag = DEFAULT_LAG_DAYS.get(period_type, 120)
    return period_end + timedelta(days=lag)


def _files_interim(reports: Sequence[object], period_type: str, today: date) -> bool:
    """Сдаёт ли компания промежуточные отчёты этого типа в последние годы."""
    since = today.year - INTERIM_LOOKBACK_YEARS
    return any(
        normalize_period_type(getattr(r, "period_type", None)) == period_type
        and (getattr(r, "fiscal_year", 0) or 0) >= since
        for r in reports
    )


def expected_periods(
    reports: Sequence[object],
    today: Optional[date] = None,
) -> List[ExpectedPeriod]:
    """
    Периоды, которые компания должна была отчитать, со статусом каждого.

    Годовые ожидаются за все годы от первого отчёта до последнего
    закончившегося. Промежуточные — только тех типов, что компания реально
    сдавала в последние годы: квартальные МСФО не обязательны никому, и ждать
    их от компании, которая их не делает, значит рисовать вечный «пропуск».
    """
    today = today or date.today()
    if not reports:
        return []

    years = [getattr(r, "fiscal_year", None) for r in reports]
    years = [y for y in years if y]
    if not years:
        return []
    first_year = min(years)

    # Индекс уже внесённых периодов
    filed: Dict[str, object] = {}
    for rep in reports:
        pt = normalize_period_type(getattr(rep, "period_type", None))
        if pt is None:
            continue
        key = _key(pt, getattr(rep, "fiscal_year", 0), getattr(rep, "fiscal_quarter", None))
        filed[key] = rep

    wanted: List[tuple[str, Optional[int]]] = [(PeriodType.ANNUAL.value, None)]
    if _files_interim(reports, PeriodType.SEMI_ANNUAL.value, today):
        wanted.append((PeriodType.SEMI_ANNUAL.value, None))
    if _files_interim(reports, PeriodType.QUARTERLY.value, today):
        wanted.extend((PeriodType.QUARTERLY.value, q) for q in (1, 2, 3))

    out: List[ExpectedPeriod] = []
    for year in range(first_year, today.year + 1):
        for period_type, quarter in wanted:
            ends = period_end_date(period_type, year, quarter)
            # Период ещё не закончился — ждать нечего
            if ends >= today:
                continue
            key = _key(period_type, year, quarter)
            deadline = deadline_for(reports, period_type, ends)
            rep = filed.get(key)
            if rep is not None:
                status: Status = "filed"
                overdue = None
            elif today <= deadline:
                status, overdue = "window_open", None
            else:
                status, overdue = "overdue", (today - deadline).days
            out.append(
                ExpectedPeriod(
                    period_type=period_type,
                    fiscal_year=year,
                    fiscal_quarter=quarter,
                    period_key=key,
                    period_label=_label(period_type, year, quarter),
                    period_end=ends,
                    deadline=deadline,
                    status=status,
                    report_id=getattr(rep, "id", None) if rep is not None else None,
                    days_overdue=overdue,
                )
            )

    out.sort(key=lambda p: (p.period_end, p.period_type), reverse=True)
    return out


# ─── Прогноз будущих публикаций ─────────────────────────────────────────────
#
# Точной даты будущей публикации не существует: закон обязывает раскрыть
# отчётность не позднее срока, но не обязывает объявлять день заранее. Поэтому
# любой календарь отчётностей — это прогноз, и вопрос лишь в том, честно ли он
# о себе говорит.
#
# Здесь прогноз строится по привычке самой компании: медиана задержки
# «отчётная дата → публикация» по её прошлым отчётам того же типа. Две вещи
# делаются иначе, чем в известных мне сервисах:
#
#   1. Дата переносится на рабочий день. Календарный перенос прошлогодней
#      даты приводит к тому, что сорок компаний «отчитываются» в субботу.
#   2. Ширина прогноза берётся из разброса. Где компания публикует в один и
#      тот же день ± неделя — показывается дата. Где разброс месяц —
#      показывается месяц, а не выдуманное число.

# Разброс лагов, при котором прогноз имеет смысл называть датой, дней.
NARROW_SPREAD_DAYS = 10
# Разброс, при котором честнее говорить о неделе.
WIDE_SPREAD_DAYS = 30

# Сколько дней назад от «сегодня» ещё показывать в календаре: отчёт мог выйти
# вчера, и человек про него не знает.
CALENDAR_LOOKBEHIND_DAYS = 10


@dataclass(frozen=True)
class UpcomingReport:
    """Ожидаемая публикация с честно названной точностью."""

    period_type: str
    fiscal_year: int
    fiscal_quarter: Optional[int]
    period_key: str
    period_label: str
    period_end: date
    expected_date: date
    # narrow — можно называть датой, wide — неделей, rough — только месяцем
    confidence: str
    lag_days: int
    lag_spread: Optional[int]
    samples: int


def lag_stats(reports: Sequence[object], period_type: str) -> tuple[Optional[int], Optional[int], int]:
    """Медиана задержки, её разброс и число наблюдений."""
    lags: List[int] = []
    for rep in reports:
        if normalize_period_type(getattr(rep, "period_type", None)) != period_type:
            continue
        filed = getattr(rep, "filing_date", None)
        ends = getattr(rep, "report_date", None)
        if filed is None or ends is None:
            continue
        lag = (filed - ends).days
        if lag > 0:
            lags.append(lag)
    if not lags:
        return None, None, 0
    if len(lags) == 1:
        return lags[0], None, 1
    return int(statistics.median(lags)), max(lags) - min(lags), len(lags)


def next_business_day(day: date) -> date:
    """Суббота и воскресенье сдвигаются на понедельник.

    Ни одна компания не публикует отчётность в выходной. Календарь, который
    переносит прошлогоднюю дату на тот же календарный день, регулярно
    показывает сорок эмитентов, «отчитывающихся» в субботу.
    """
    while day.weekday() >= 5:
        day = day + timedelta(days=1)
    return day


def _confidence(spread: Optional[int], samples: int) -> str:
    if samples == 0:
        return "rough"
    if spread is None:
        return "wide"
    if spread <= NARROW_SPREAD_DAYS:
        return "narrow"
    if spread <= WIDE_SPREAD_DAYS:
        return "wide"
    return "rough"


def _interim_lag_from_annual(reports: Sequence[object], period_type: str) -> Optional[int]:
    """Оценка задержки промежуточного отчёта по привычке в годовом.

    У большинства компаний полугодовых отчётов в базе нет, и все они падают
    на общий дедлайн — календарь превращается в один столбец из ста тридцати
    тикеров. Между тем привычка компании видна по годовому отчёту: кто сдаёт
    годовой на 57-й день из 120 возможных, тот и полугодовой сдаёт в первой
    половине окна.

    Поэтому доля пройденного срока переносится с годового на промежуточный.
    Точностью это не является и помечается как `rough`, но даёт правдоподобный
    разброс вместо ложной кучи в одну дату.
    """
    annual_median, _, samples = lag_stats(reports, PeriodType.ANNUAL.value)
    if annual_median is None or samples == 0:
        return None
    annual_window = DEFAULT_LAG_DAYS[PeriodType.ANNUAL.value]
    own_window = DEFAULT_LAG_DAYS.get(period_type, 60)
    share = min(annual_median / annual_window, 1.0)
    return max(int(round(share * own_window)), 7)


def upcoming_reports(
    reports: Sequence[object],
    today: Optional[date] = None,
    horizon_days: int = 150,
) -> List[UpcomingReport]:
    """
    Отчёты, публикации которых стоит ждать в ближайшие месяцы.

    Берутся периоды, которые компания обычно сдаёт, ещё не внесённые в базу, с
    прогнозной датой в окне от `CALENDAR_LOOKBEHIND_DAYS` назад до
    `horizon_days` вперёд. Прогноз — конец периода плюс медианная задержка
    этой компании, перенесённый на рабочий день.
    """
    today = today or date.today()
    if not reports:
        return []

    horizon = today + timedelta(days=horizon_days)
    behind = today - timedelta(days=CALENDAR_LOOKBEHIND_DAYS)

    filed = {
        _key(
            normalize_period_type(getattr(r, "period_type", None)) or "",
            getattr(r, "fiscal_year", 0),
            getattr(r, "fiscal_quarter", None),
        )
        for r in reports
    }

    # Полугодовая отчётность ожидается от всех, а не только от тех, чьи
    # полугодовые уже лежат в базе. Это намеренное отличие от `expected_periods`:
    #
    #   * там вопрос «что я пропустил», и лишнее ожидание создаёт ложный
    #     пропуск — шум в списке дел;
    #   * здесь вопрос «чего ждать», и ошибиться в сторону лишней строки
    #     ничего не стоит: отчёт либо выйдет, либо нет.
    #
    # Плюс отсутствие полугодового отчёта в базе означает лишь то, что мы его
    # не заносили. Для компаний в котировальных списках полугодовая МСФО —
    # норма, и делать вид, что её не будет, значит показывать пустой календарь.
    #
    # Квартальные остаются по истории: они не обязательны никому, их сдаёт
    # меньшинство, и ждать их от всех — уже не осторожность, а выдумка.
    wanted: List[tuple[str, Optional[int]]] = [
        (PeriodType.ANNUAL.value, None),
        (PeriodType.SEMI_ANNUAL.value, None),
    ]
    if _files_interim(reports, PeriodType.QUARTERLY.value, today):
        wanted.extend((PeriodType.QUARTERLY.value, q) for q in (1, 2, 3))

    out: List[UpcomingReport] = []
    for year in (today.year, today.year + 1):
        for period_type, quarter in wanted:
            key = _key(period_type, year, quarter)
            if key in filed:
                continue
            ends = period_end_date(period_type, year, quarter)
            median, spread, samples = lag_stats(reports, period_type)
            if median is not None:
                lag = median
            else:
                # Своей истории по этому типу нет: пробуем перенести привычку
                # с годового отчёта, и только потом падаем на общий срок.
                lag = _interim_lag_from_annual(reports, period_type) or DEFAULT_LAG_DAYS.get(
                    period_type, 120
                )
            expected = next_business_day(ends + timedelta(days=lag))
            if not (behind <= expected <= horizon):
                continue
            out.append(
                UpcomingReport(
                    period_type=period_type,
                    fiscal_year=year,
                    fiscal_quarter=quarter,
                    period_key=key,
                    period_label=_label(period_type, year, quarter),
                    period_end=ends,
                    expected_date=expected,
                    confidence=_confidence(spread, samples),
                    lag_days=lag,
                    lag_spread=spread,
                    samples=samples,
                )
            )

    out.sort(key=lambda u: u.expected_date)
    return out


__all__ = (
    "DEFAULT_LAG_DAYS",
    "ExpectedPeriod",
    "LAG_MARGIN_DAYS",
    "deadline_for",
    "expected_periods",
    "lag_stats",
    "median_lag_days",
    "next_business_day",
    "normalize_period_type",
    "period_end_date",
    "upcoming_reports",
)
