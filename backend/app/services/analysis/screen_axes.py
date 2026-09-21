"""Семь осей описания компании — величины без порогов.

Глава 13 «Разумного инвестора» — не фильтр, а перечень направлений, по которым
компанию положено описывать: рентабельность, стабильность, рост, финансовое
положение, дивиденды, динамика цен. Порогов там нет ни одного: Грэм сравнивает
четыре компании и показывает, *что* смотреть, а не *где* граница. Границы стоят
в двух других местах и разные — гл. 14 для защитного инвестора (с. 371–372) и
гл. 15 для активного (с. 419). Между «20 лет дивидендов» и «платит сейчас»
среднего не существует, поэтому объединять их в один список нельзя.

Отсюда разделение, на котором держится весь модуль:

    ось     что измеряем  — одинаково для банка и для нефтяника
    порог   чем меряем    — зависит от строгости, отрасли и рынка

**Здесь нет ни одного порога.** Ни книжного, ни отраслевого. Модуль считает
величины и отдаёт их вместе с рядом по годам; накладывает пороги `screen`,
беря их из `sector_profiles`. Смысл разделения практический: когда порог и
величина живут в одном месте, невозможно ответить, почему компания не прошла —
из-за плохого показателя или из-за того, что к ней применили чужую мерку.

Восьмая ось — размер — у Грэма стоит в гл. 14 и в гл. 13 не упоминается, но
измеряется так же, поэтому лежит здесь вместе с остальными.

**Рентабельность — наше расширение.** У Грэма это ось описания, порога по ROE
нет ни в защитном списке, ни в активном. В проекте она несёт вес: через неё
считается устойчивый рост в множителе рынка. Помнить об этом стоит как о своём
решении, а не как о требовании книги.

**Деньгам своя колонка.** Рядом с прибылью везде, где это осмысленно, идёт та
же величина по свободному потоку: рентабельность по FCF рядом с ROE,
безубыточность по FCF рядом с безубыточностью по прибыли. У кредитных
организаций поток клиентских денег к собственным деньгам компании отношения не
имеет, поэтому там эти подметрики не считаются вовсе — то же правило, по
которому работает `analyze(with_cash=...)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.analysis.earning_power import (
    graham_growth,
    load_points,
    window_average,
)

# Окно для средних уровней: гл. 11 велит брать семь–десять лет.
LEVEL_WINDOW = 7
# P/E защитного инвестора считается по средней прибыли за три года (гл. 14).
# Здесь это только величина; порог 15 или 9 ставит `screen`.
PRICE_WINDOW = 3
# Горизонты проверки на убытки: защитному инвестору Грэм отводит десять лет
# (гл. 14), активному — пять (гл. 15). Считаются оба, потому что «нет убытков
# за десять лет» и «нет убытков за пять» — разные утверждения, и подменять
# одно другим значит менять строгость молча.
# Насколько должен просесть капитал от достигнутого пика, чтобы рост отдачи на
# него объяснялся знаменателем, а не прибылью. Величина — суждение: доли
# процента бывают у любой компании, а пятая часть капитала просто так не
# исчезает.
EQUITY_SHRINK = 0.15
# Отдача выше этой доли означает не выдающийся бизнес, а крошечный
# знаменатель: прибыль за год превысила весь капитал. Граница не назначена, а
# следует из смысла дроби — выше неё числитель больше знаменателя, и отношение
# начинает описывать структуру капитала вместо прибыльности дела. Тем же
# порогом таблица мультипликаторов помечает ROE как «Искажено».
RETURN_DISTORTED = 100.0

STABILITY_SPAN = 10
STABILITY_SPAN_SHORT = 5
# Десятилетие для теста роста, концы сглажены тройками (гл. 14).
GROWTH_SPAN = 10
# Активному инвестору Грэм ставит проще: прибыль последнего года выше, чем
# пять лет назад (гл. 15). Сглаживания он там не назначает, но мы его вводим:
# два одиночных года по краям отдают весь ответ случайностям этих двух лет. У
# Лукойла прибыль за 2025 год записана по продолжающейся деятельности и вышла
# 158 ₽ против 1252 ₽ годом раньше — сравнение одиночных лет дало −86,7%,
# сравнение пар −39,5%. Второе число ближе к тому, что происходит с
# компанией, и ради него стоит отступить от буквы: сглаживание концов — тот
# самый приём, который сам Грэм применяет в десятилетнем тесте гл. 14.
# Тройки в пять лет не помещаются (нужно шесть), поэтому пары.
#
# «Пять лет назад» — это 2020 год для отчётности за 2025-й, то есть **шесть**
# календарных точек, а не пять. Окно в пять лет даёт 2021–2025: между концами
# четыре года, а тот самый год, с которым велено сравнивать, выброшен вовсе.
# У Лукойла ошибка на единицу меняла ответ на противоположный — −39,5% против
# +16,3% по прибыли и −5,2% против +68,5% по потоку, при том что за пять лет
# выросло и то, и другое.
GROWTH_YEARS_BACK_SHORT = 5
GROWTH_SPAN_SHORT = GROWTH_YEARS_BACK_SHORT + 1
GROWTH_SMOOTH_SHORT = 2
# Сглаживание для пятилетнего отрезка по свободному потоку: пары с каждого
# конца. Тройки в пять лет не помещаются, а одиночные годы для потока слишком
# шумны — он дёргается вместе с оборотным капиталом и волнами капекса.
CASH_SMOOTH_SHORT = 2
# Выше этого **годового** темпа ряду верить нельзя. Считать по итоговым
# процентам оказалось нельзя: Новабев даёт +1 122% за десятилетие при
# совершенно чистом ряде — прибыль выросла с 275 млн до 5 169 млн, выручка с
# 35,9 до 149,3 млрд, — и прежний порог в 1 000% объявлял её испорченной.
# Годовой темп сопоставим между окнами разной длины: 43% в год семь лет
# подряд бывает, 90% в год десять лет — нет.
GROWTH_SANITY_ANNUAL = 60.0
# Маржа выше этой доли выручки означает, что в числителе не та величина.
# Порог с большим запасом: у холдинга доход по методу долевого участия может
# превысить собственную выручку, и такие случаи отсекать не надо.
MARGIN_SANITY = 200.0


@dataclass(frozen=True)
class Metric:
    """Одна подметрика оси: величина, ряд по годам и то, из чего она вышла.

    Ось редко сводится к одному числу. Финансовое положение — это ликвидность,
    долг к капиталу и чистый долг сразу, и они умеют противоречить друг другу:
    текущая ликвидность ниже единицы при полном отсутствии долга — обычное
    дело для добычи. Свести их к одной цифре значит выбросить именно то, ради
    чего ось смотрят.
    """

    key: str
    label: str
    value: Optional[float]
    unit: str = ""
    # Знаменатель там, где величина — это «столько-то из стольких-то».
    of: Optional[float] = None
    # Средняя за `LEVEL_WINDOW` лет, где усреднение осмысленно.
    average: Optional[float] = None
    # Ряд по годам для динамики: ((год, величина), ...).
    series: tuple = ()
    # Годы, которые эту подметрику испортили: убыточные, отрицательные.
    flagged: tuple = ()
    # Почему величины нет или почему она читается иначе, чем выглядит.
    note: Optional[str] = None
    # На когда величина: «LTM» или год. Смешивать скользящий год с календарным
    # молча нельзя — у Лукойла отдача на капитал за 2025 год 10,5%, а за
    # последние двенадцать месяцев 17,3%, и это разные утверждения.
    asof: Optional[str] = None
    # Сторона нуля, на которой величина, — «good» или «bad».
    #
    # **Это не порог.** Порогов модуль не знает и знать не должен. Здесь только
    # то, что читается из самого числа: убыток есть убыток, отрицательный
    # чистый долг означает, что денег больше, чем займов, а «10 из 10» лучше,
    # чем «8 из 10». Где сторона нуля ничего не значит — у текущей ликвидности,
    # у P/E — пометки нет, и цвет там берётся только из вердикта.
    tone: Optional[str] = None
    # Почему величине нельзя верить. Заполняется, когда число получилось
    # арифметически, но противоречит здравому смыслу: испорченная строка
    # прибыли давала десятилетний рост около 90% в год, а так не бывает.
    # Считать такое пройденным критерием хуже, чем признать, что мы не знаем.
    #
    # Порог здесь легко перестараться. Ровно это и вышло в первой редакции:
    # проверка стояла на итоговых процентах, и настоящий рост Новабев на
    # +1 122% за десятилетие она объявляла испорченными данными. Пометка
    # обязана срабатывать на невозможном, а не на выдающемся.
    suspect: Optional[str] = None

    @property
    def known(self) -> bool:
        return self.value is not None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "value": None if self.value is None else round(self.value, 4),
            "unit": self.unit,
            "of": self.of,
            "average": None if self.average is None else round(self.average, 4),
            "series": [[y, round(v, 4)] for y, v in self.series],
            "flagged": list(self.flagged),
            "note": self.note,
            "asof": self.asof,
            "tone": self.tone,
            "suspect": self.suspect,
        }


@dataclass(frozen=True)
class Axis:
    """Одна из осей главы 13 со всеми её подметриками.

    `lead` — ключ подметрики, по которой ось получает приговор. Остальные
    стоят рядом справочно и в бинарный вердикт не входят: FCF отрицателен в
    двух годах — это повод пометить ось, а не завалить её.
    """

    key: str
    label: str
    metrics: tuple = ()
    lead: Optional[str] = None
    note: Optional[str] = None

    def metric(self, key: str) -> Optional[Metric]:
        for m in self.metrics:
            if m.key == key:
                return m
        return None

    @property
    def lead_metric(self) -> Optional[Metric]:
        return None if self.lead is None else self.metric(self.lead)

    @property
    def measurable(self) -> bool:
        """Есть ли вообще что оценивать. Пустая ось — не провал, а нехватка."""
        return any(m.known for m in self.metrics)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "lead": self.lead,
            "measurable": self.measurable,
            "note": self.note,
            "metrics": [m.as_dict() for m in self.metrics],
        }


# ─── Вспомогательное ────────────────────────────────────────────────────────

def _sorted(points) -> list:
    return sorted(points, key=lambda p: p.year)


def _series(points, attr: str) -> tuple:
    """Ряд по годам без пропусков и без None."""
    return tuple(
        (p.year, float(getattr(p, attr)))
        for p in _sorted(points)
        if getattr(p, attr, None) is not None
    )


def _last(series: tuple) -> Optional[float]:
    return series[-1][1] if series else None


def _average(points, attr: str, window: int = LEVEL_WINDOW):
    """Средняя за окно — и причина, если её не будет.

    Ряд, пересекающий ноль, усреднять нельзя: у Озона капитал уходил в минус,
    и отдача на него за семь лет выходит 129% — величина, собранная из
    отрицательных знаменателей и не значащая ничего. Молча показать её хуже,
    чем не показать вовсе.
    """
    avg = window_average(points, attr, window)
    if avg is None:
        return None, None
    if avg.crosses_zero:
        return None, "Среднее не считается: ряд пересекает ноль"
    return avg.value, None


# Метка скользящего года. Стоит рядом с каждой величиной, взятой из свежего
# среза, — чтобы её нельзя было спутать с календарным годом.
LTM = "LTM"


def _live(live, attr: str) -> Optional[float]:
    """Величина из свежего среза кэша, если она там есть."""
    value = None if live is None else getattr(live, attr, None)
    return None if value is None else float(value)


def _fresh(live, attr: str, fallback: Optional[float], year: Optional[int] = None):
    """Пара «величина, на когда»: свежий срез, иначе последний годовой.

    Экран судит по цене, которую платят сейчас, а не по цене на конец года.
    У Лукойла на 31.12.2025 акция стоила 5 880 ₽, сегодня 4 554 ₽ — разница в
    29%, и порог P/E, посчитанный по старой цене, проверял бы не ту сделку.
    """
    value = _live(live, attr)
    if value is not None:
        return value, LTM
    return fallback, (str(year) if year is not None else None)


def _tone(value: Optional[float], higher_is_better: bool = True) -> Optional[str]:
    """Сторона нуля. Не порог: убыток есть убыток при любой мерке."""
    if value is None:
        return None
    if value == 0:
        return None
    positive = value > 0
    return "good" if positive == higher_is_better else "bad"


def _denominator_verdict(value: Optional[float], mults: dict, series: tuple):
    """Цвет, пояснение и недоверие для отдачи на капитал: (tone, note, suspect).

    У отношения два конца, и испортиться может любой. Проверяем оба, в
    порядке от сильного к слабому:

    **Знаменателя нет.** Отдача выше ста процентов означает, что прибыль за
    год превысила весь капитал. Выдающимся бизнесом это почти никогда не
    бывает; бывает крошечный знаменатель. У МТС капитал ходит вокруг нуля —
    14,6 млрд, потом −3,6, потом 1,7, потом −11,2 — и отдача выходит 440%,
    −924%, 3 228%. Ни одно из этих чисел не описывает бизнес: они описывают
    структуру капитала. Правило то же, по которому таблица мультипликаторов
    пишет «Искажено», и второго правила заводить не надо.

    **Знаменатель сжался.** Отдача выросла за год, а капитал за тот же год
    ужался — рост пришёл не с той стороны дроби. Случай Новабев.

    В первом случае величина ещё и не годится для сравнения с порогом.
    Отдача 228% формально проходит «≥ 20%», но проходит она как измерение
    структуры капитала, а не прибыльности дела: сравнивать её с порогом,
    выведенным для нормального знаменателя, значит выдавать искажение за
    достижение. Поэтому вместе с цветом возвращается недоверие, и критерий
    остаётся неизмеренным.

    Во втором величина годится: рост пришёл не с той стороны дроби, но сама
    отдача сопоставима с порогом. Там меняется только цвет.

    Ложной величина не объявляется нигде: она посчитана верно.
    """
    if value is not None and abs(value) > RETURN_DISTORTED:
        distorted = ("Отдача больше всего капитала: величина посчитана верно, "
                     "но измеряет структуру капитала, а не прибыльность дела")
        return "warn", distorted, distorted
    if _shrinking_denominator(mults, series):
        return "warn", None, None
    return _tone(value), None, None


def _shrinking_denominator(mults: dict, series: tuple) -> bool:
    """Отдача выросла за год, а капитал под ней за тот же год ужался.

    Отношение растёт двумя способами, и означают они противоположное. У
    Новабев отдача на капитал поднялась с 17,2% до 23,6% не на прибыли, а на
    выкупе и выплатах: капитал за тот же год ушёл с 26,7 до 21,9 млрд.
    Показать это зелёным значит назвать достижением то, что достижением не
    является, — ровно та ошибка, ради которой на дробь положено смотреть с
    обоих концов.

    Смотрим **общий** капитал, а не на акцию: знаменатель отдачи — именно он,
    и выкуп акций уменьшает его сильнее, чем величину на акцию. У Новабев
    капитал на акцию просел на 8,5%, а весь — на 18%, и настоящий здесь
    второй. Сравниваем с прошлым годом, а не с давним пиком: событие
    произошло в этом году, и старый пик мог быть до другой жизни компании.

    Величина не объявляется ложной: она посчитана верно. Меняется только
    цвет — с «хорошо» на «посмотри внимательнее».
    """
    if len(series) < 2:
        return False
    (before_year, before_roe), (last_year, last_roe) = series[-2], series[-1]
    if last_roe <= before_roe:
        return False

    def equity(year):
        mult = mults.get(year)
        value = None if mult is None else getattr(mult, "equity", None)
        return None if value is None else float(value)

    before, now = equity(before_year), equity(last_year)
    if not before or now is None or before <= 0:
        return False
    return now < before * (1 - EQUITY_SHRINK)


def _tone_full(value: Optional[float], of: Optional[float]) -> Optional[str]:
    """«Столько-то из стольких-то»: полный счёт — good, неполный — bad."""
    if value is None or not of:
        return None
    return "good" if value >= of else "bad"


def _return_on_equity(points, attr: str):
    """Отдача на капитал — только за годы, когда капитал положителен.

    При отрицательном капитале знак сокращается, и убыток выходит прибылью: у
    Озона за 2025 год убыток −4,36 ₽ на акцию делится на капитал −689,6 ₽ и
    даёт «отдачу 0,63%». Ряд при этом ноль не пересекает — все пять значений
    положительны, — поэтому обычная проверка на смену знака здесь бессильна, и
    смотреть надо на знаменатель.

    Если капитал отрицателен в последнем году, не считается ни величина, ни
    средняя: средняя по уцелевшим годам была бы посчитана за другой отрезок
    времени, чем написано на ярлыке.
    """
    rows = _sorted(points)
    known = [p for p in rows if getattr(p, attr, None) is not None]
    if not known:
        return None, None, (), (), None

    usable = [p for p in known
              if p.book_value_per_share is not None and p.book_value_per_share > 0]
    dropped = tuple(p.year for p in known if p not in usable)
    series = tuple((p.year, float(getattr(p, attr))) for p in usable)

    if not usable or usable[-1].year != known[-1].year:
        note = (f"Капитал отрицателен с {min(dropped)} года — "
                f"отдача на него не считается") if dropped else None
        return None, None, series, dropped, note

    average, note = _average(usable, attr)
    if dropped and note is None:
        note = f"Годы с отрицательным капиталом исключены: {_years(dropped)}"
    return float(getattr(usable[-1], attr)), average, series, dropped, note


def _normalised_roe(mults: dict, year: Optional[int]) -> Optional[float]:
    """Отдача за один год от очищенной прибыли — как в таблице мультипликаторов."""
    mult = mults.get(year)
    value = None if mult is None else getattr(mult, "roe", None)
    return None if value is None else float(value)


def _years(years: tuple) -> str:
    return ", ".join(str(y) for y in years)


def _loss_free(points, attr: str, span: int = STABILITY_SPAN):
    """Сколько лет из последних `span` закончены без убытка.

    Окно отсчитывается по календарю от последнего известного года, а не по
    числу заполненных строк: дыра в середине не должна превращать десятилетие
    в восьмилетие под тем же именем. Знаменателем идёт число лет, за которые
    величина вообще известна.
    """
    series = _series(points, attr)
    if not series:
        return None, None, ()
    last = series[-1][0]
    window = [(y, v) for y, v in series if y > last - span]
    losses = tuple(y for y, v in window if v <= 0)
    return len(window) - len(losses), len(window), losses


def _growth_percent(points, attr: str, span: int = GROWTH_SPAN,
                    smooth: int = 3) -> Optional[float]:
    percent, _ = _growth_with_gap(points, attr, span, smooth)
    return percent


def _growth_with_gap(points, attr: str, span: int = GROWTH_SPAN, smooth: int = 3):
    """Прирост и расстояние между серединами сглаженных концов, в годах.

    Расстояние нужно, чтобы судить о правдоподобии: «+1 122%» само по себе не
    говорит ничего, а «+43% в год семь лет подряд» — говорит.
    """
    direction = graham_growth(points, attr, span=span, smooth=smooth)
    if direction is None or direction.change is None:
        return None, None
    older = sum(direction.older_years) / len(direction.older_years)
    newer = sum(direction.newer_years) / len(direction.newer_years)
    return direction.change * 100.0, newer - older


def _dividend_history(points) -> tuple:
    """Серия подряд, всего оплаченных лет и длина доступной истории.

    Две величины, а не одна, потому что они расходятся и расходятся осмысленно.
    У Норникеля выплаты шли годами, но последние два года пропущены — серия
    обрывается в ноль, тогда как платил он большую часть истории. Показать
    только серию значит объявить его никогда не платившим; показать только
    сумму лет — скрыть, что выплаты прекратились.

    Признаком выплаты считается либо сумма, либо отметка «дивиденды
    объявлялись». Второе обязательно: у части компаний сумма в базу не
    занесена, и без этой проверки «не записали» читается как «не платит» —
    ошибка, из-за которой честно платящая компания получает отказ.
    """
    rows = _sorted(points)
    if not rows:
        return 0, 0, 0

    def paid(point) -> bool:
        amount = point.dividends_per_share
        return (amount is not None and amount > 0) or point.dividends_declared is True

    streak = 0
    for point in reversed(rows):
        if not paid(point):
            break
        streak += 1
    return streak, sum(1 for p in rows if paid(p)), len(rows)


def _mult_series(mults: dict, attr: str) -> tuple:
    return tuple(
        (year, float(getattr(mult, attr)))
        for year, mult in sorted(mults.items())
        if getattr(mult, attr, None) is not None
    )


# ─── Оси ────────────────────────────────────────────────────────────────────

def profitability(points, mults: dict, reports: dict, is_lender: bool,
                  live=None) -> Axis:
    """Рентабельность. Порога у Грэма нет — это ось описания."""
    value, average, series, dropped, note = _return_on_equity(points, "roe")
    year = series[-1][0] if series else None

    # Отдельно взятый год считается по очищенной прибыли, многолетняя средняя —
    # по отчётной. Правило то же, что для P/E: разовые статьи в одном году
    # искажают его целиком, а на длинном окне средняя их поглощает, и вычищать
    # каждый год по отдельности значит систематически льстить.
    #
    # А сам «отдельно взятый год» — это последние двенадцать месяцев, а не
    # календарный: у Лукойла за 2025 год отдача 10,5%, за скользящий год
    # 17,3%, и вторая величина отвечает на вопрос «сколько компания
    # зарабатывает сейчас», ради которого её и смотрят.
    if value is not None:
        # Порядок отступления: скользящий год, затем очищенная величина за
        # последний календарный, и только потом отчётная, посчитанная здесь.
        fallback = _normalised_roe(mults, year)
        value, asof = _fresh(live, "roe", value if fallback is None else fallback, year)
        note = note or "Сейчас — по очищенной прибыли, средняя за 7 лет — по отчётной"
    else:
        asof = None

    tone, denominator_note, distorted = _denominator_verdict(value, mults, series)
    if tone == "warn":
        note = denominator_note or "Отдача выросла на уменьшении капитала, а не на прибыли"

    metrics = [
        Metric(
            key="roe", label="Отдача на капитал", unit="%",
            value=value, average=average, series=series, flagged=dropped,
            asof=asof, tone=tone, suspect=distorted,
            note=note or "Считается от отчётной прибыли, а не от очищенной",
        )
    ]
    if not is_lender:
        cash, cash_average, cash_series, cash_dropped, cash_note = (
            _return_on_equity(points, "fcf_to_equity")
        )
        cash_asof = str(cash_series[-1][0]) if cash_series else None
        if cash is not None:
            live_cash = _live_fcf_to_equity(live)
            if live_cash is not None:
                cash, cash_asof = live_cash, LTM
        # Знаменатель тот же самый, поэтому и оговорки те же: поток к капиталу
        # искажается крошечным капиталом и растёт от его сжатия ровно так же,
        # как отдача на него.
        cash_tone, cash_denominator, cash_distorted = _denominator_verdict(
            cash, mults, cash_series)
        if cash_tone == "warn":
            cash_note = (cash_denominator
                         or "Выросло на уменьшении капитала, а не на потоке")
        metrics.append(Metric(
            key="fcf_to_equity", label="Свободный поток к капиталу", unit="%",
            value=cash, average=cash_average, series=cash_series,
            flagged=cash_dropped, note=cash_note,
            asof=cash_asof, tone=cash_tone, suspect=cash_distorted,
        ))

    roa = _return_on_assets(mults, reports)
    if is_lender:
        # Коэффициент издержек — то же, что операционная эффективность у
        # промышленной компании. Судить по нему надо по средней: разовая
        # экономия дисциплины не доказывает, она видна только на отрезке.
        cir = _mult_series(mults, "cost_to_income")
        cir_now, cir_asof = _fresh(live, "cost_to_income", _last(cir), _year(cir))
        metrics.append(Metric(
            key="cost_to_income", label="Издержки к доходам", unit="%",
            value=cir_now, series=cir, asof=cir_asof,
            note="Меньше — лучше. Порог из отраслевого профиля",
        ))
        metrics.append(Metric(
            key="cost_to_income_average",
            label=f"То же в среднем за {LEVEL_WINDOW} лет", unit="%",
            value=_mean(cir), series=cir,
            note="По средней и судим: показатель описывает поведение, а не запас",
        ))
        margin = _bank_series(reports)["net_interest_margin"]
        metrics.append(Metric(
            key="net_interest_margin", label="Чистая процентная маржа", unit="%",
            value=_last(margin), series=margin, average=_mean(margin),
            note="Процентный доход к активам",
        ))

    roa_value, roa_asof = _live_return_on_assets(live), LTM
    if roa_value is None:
        roa_value = _last(roa)
        roa_asof = str(roa[-1][0]) if roa else None
    metrics.append(Metric(
        key="roa", label="Отдача на активы", unit="%",
        value=roa_value, series=roa, asof=roa_asof, tone=_tone(roa_value),
        note="Под вопросом: в вердикте пока не участвует",
    ))

    # Маржа отвечает на другой вопрос, чем отдача на капитал. Отдача говорит,
    # много ли компания зарабатывает на вложенные деньги, и её легко поднять
    # плечом: у Белуги отдача 23,6% при долге к капиталу 4,8. Маржа говорит,
    # сколько остаётся с рубля выручки, и заёмными деньгами не подделывается.
    for key, label, profit_attr, flow in (
        ("net_margin", "Маржа по прибыли", "net_income_reported", False),
        ("fcf_margin", "Маржа по FCF", None, True),
    ):
        if flow and is_lender:
            continue
        series = _margin_series(mults, reports, flow)
        value, asof = _live_margin(live, flow), LTM
        if value is None:
            value = _last(series)
            asof = str(series[-1][0]) if series else None
        # Маржа выше выручки означает, что в числителе не та величина:
        # перепутанная строка прибыли даёт компании, живущей на трёх
        # процентах, среднюю за семь лет под шестьдесят.
        broken = tuple(y for y, v in series if abs(v) > MARGIN_SANITY)
        recent = series[-LEVEL_WINDOW:]
        average = (sum(v for _, v in recent) / len(recent)) if recent else None
        metrics.append(Metric(
            key=key, label=label, unit="%",
            value=value, average=None if broken else average, series=series,
            asof=asof, tone=_tone(value), flagged=broken,
            suspect=(f"Маржа выше выручки в {_years(broken)} — "
                     f"в числителе не та величина") if broken else None,
        ))

    return Axis(
        key="profitability", label="Рентабельность",
        metrics=tuple(metrics), lead="roe",
        note="Наше расширение: порога по рентабельности у Грэма нет",
    )


def _live_fcf_to_equity(live) -> Optional[float]:
    """Свободный поток к капиталу за скользящий год.

    Поток берётся очищенный от клиентских денег там, где он посчитан: у биржи
    и гибрида валовой поток описывает чужие средства, а не собственные.
    """
    flow = _live(live, "ltm_core_fcf")
    if flow is None:
        flow = _live(live, "ltm_fcf")
    equity = _live(live, "equity")
    if flow is None or not equity or equity <= 0:
        return None
    return flow / equity * 100.0


def _margin_series(mults: dict, reports: dict, flow: bool) -> tuple:
    """Маржа по годам: сколько остаётся с рубля выручки.

    Прибыль берётся отчётная — то же правило, что и для всех многолетних
    рядов. Поток берётся очищенный от клиентских денег там, где он посчитан.
    """
    from app.services.analysis.multiplier_service import _field_rub
    from app.services.analysis.earning_power import own_cash_flow

    out = []
    for year, mult in sorted(mults.items()):
        revenue = None if mult.ltm_revenue is None else float(mult.ltm_revenue)
        if not revenue or revenue <= 0:
            continue
        if flow:
            numerator = own_cash_flow(mult)
        else:
            report = reports.get(year)
            numerator = None if report is None else _field_rub(report, "net_income_reported")
        if numerator is None:
            continue
        out.append((year, numerator / revenue * 100.0))
    return tuple(out)


def _live_margin(live, flow: bool) -> Optional[float]:
    revenue = _live(live, "ltm_revenue")
    if not revenue or revenue <= 0:
        return None
    if flow:
        numerator = _live(live, "ltm_core_fcf")
        if numerator is None:
            numerator = _live(live, "ltm_fcf")
    else:
        numerator = _live(live, "ltm_net_income")
    return None if numerator is None else numerator / revenue * 100.0


def _live_return_on_assets(live) -> Optional[float]:
    profit = _live(live, "ltm_net_income")
    assets = _live(live, "total_assets")
    if profit is None or not assets:
        return None
    return profit / assets * 100.0


def _return_on_assets(mults: dict, reports: dict) -> tuple:
    """Отдача на активы — от той же отчётной прибыли, что и остальной ряд."""
    from app.services.analysis.multiplier_service import _field_rub

    out = []
    for year, mult in sorted(mults.items()):
        report = reports.get(year)
        assets = None if mult.total_assets is None else float(mult.total_assets)
        profit = None if report is None else _field_rub(report, "net_income_reported")
        if not assets or profit is None:
            continue
        out.append((year, profit / assets * 100.0))
    return tuple(out)


def stability(points, is_lender: bool, reports: Optional[dict] = None,
              ltm_bank: Optional[dict] = None) -> Axis:
    """Стабильность: годы без убытка. Гл. 14 — десять лет, гл. 15 — пять."""
    profit_free, profit_of, profit_losses = _loss_free(points, "eps")
    short_free, short_of, short_losses = _loss_free(
        points, "eps", STABILITY_SPAN_SHORT,
    )
    metrics = [
        Metric(
            key="profitable_years", label="Годы без убытка по прибыли", unit="лет",
            value=None if profit_free is None else float(profit_free),
            of=profit_of, flagged=profit_losses,
            tone=_tone_full(profit_free, profit_of),
        ),
        Metric(
            key="profitable_years_short",
            label=f"То же за последние {STABILITY_SPAN_SHORT} лет", unit="лет",
            value=None if short_free is None else float(short_free),
            of=short_of, flagged=short_losses,
            tone=_tone_full(short_free, short_of),
            note="Горизонт активного инвестора (гл. 15)",
        ),
    ]

    if not is_lender:
        cash_free, cash_of, cash_losses = _loss_free(points, "fcf_per_share")
        metrics.append(Metric(
            key="cash_positive_years", label="Годы без оттока по FCF", unit="лет",
            value=None if cash_free is None else float(cash_free),
            of=cash_of, flagged=cash_losses,
            tone=_tone_full(cash_free, cash_of),
            note="Наше добавление; к кредитным организациям не применяется",
        ))

    if is_lender and reports:
        # Стоимость риска — главное число банка через цикл. В хороший год она
        # низкая у всех; вопрос, какой была в плохой. Поэтому судим по средней
        # и показываем пик рядом.
        risk = _bank_series(reports)["cost_of_risk"]
        # Средняя за цикл — по годовым: скользящий год в неё подмешивать
        # нельзя, последний год посчитался бы дважды. Но пик берём с учётом
        # LTM, иначе свежее ухудшение осталось бы за кадром.
        fresh, _ = _bank_fresh(ltm_bank, "cost_of_risk", risk)
        peak = max([v for _, v in risk] + ([fresh] if fresh is not None else []),
                   default=None)
        metrics.append(Metric(
            key="cost_of_risk_average",
            label=f"Стоимость риска в среднем за {LEVEL_WINDOW} лет", unit="%",
            value=_mean(risk), series=risk, average=peak,
            note="Рядом — пик за историю. Сколько портфеля банк списывает ежегодно",
        ))

    return Axis(
        key="stability", label="Стабильность",
        metrics=tuple(metrics), lead="profitable_years",
    )


def _implausible(value: Optional[float], gap: Optional[float] = None) -> Optional[str]:
    """Не выходит ли прирост за пределы возможного.

    Судить по итоговым процентам нельзя: «+1 122% за десятилетие» звучит
    невозможно, а на деле это Новабев, у которого прибыль выросла с 275 млн до
    5 169 млн при выручке с 35,9 до 149,3 млрд — рост настоящий, просто база
    2016 года лежит в яме 2015-го. Прежний порог в 1 000% объявлял такую
    компанию испорченной строкой, то есть врал: ряд у неё чистый.

    Смотреть надо на **годовой** темп, потому что он сопоставим между окнами
    разной длины и с тем, что вообще бывает. `GROWTH_SANITY_ANNUAL` — та
    граница, выше которой публичная компания не держится годами; случай, ради
    которого проверка заводилась, давал около 90% в год десять лет подряд.
    """
    if value is None or value <= 0:
        return None
    if not gap or gap <= 0:
        return None
    annual = ((1 + value / 100.0) ** (1 / gap) - 1) * 100.0
    if annual < GROWTH_SANITY_ANNUAL:
        return None
    return (f"Это {annual:.0f}% в год {gap:.0f} лет подряд — так не бывает, "
            f"в ряду испорчен хотя бы один год")


DILUTION_NOTE_PCT = 15.0


def _dilution_note(points, span: int, smooth: int) -> Optional[str]:
    """Почему прибыль в таблице растёт, а прирост на акцию — нет.

    Тест гл. 14 меряет прибыль НА АКЦИЮ, и это не придирка к формулировке:
    рост, оплаченный выпуском новых акций, прежнему акционеру не достался.
    У ДОМ.РФ прибыль с 2018 по 2025 выросла в 4,7 раза, а число акций — в 3,9
    (государство докапитализировало компанию, потом IPO), и на акцию от роста
    почти ничего не осталось: 416 ₽ против 494 ₽ за семь лет.

    Без этой строки человек видит в таблице прибыль, растущую год за годом,
    и минус в тесте роста — и решает, что ошибся расчёт. Ошибки нет, но
    объяснить разницу должен сам показатель, а не переписка с автором.

    Окно берётся то же, что и у самого теста: сравнивать прирост акций за
    десять лет с приростом прибыли за пять значило бы объяснять одно другим.
    """
    shares = graham_growth(points, "shares_normalized", span=span, smooth=smooth)
    if shares is None or shares.change is None:
        return None
    percent = shares.change * 100.0
    if percent < DILUTION_NOTE_PCT:
        return None
    return (f"Число акций за то же окно выросло на {percent:.0f}%: "
            f"часть прироста прибыли оплачена выпуском новых акций, "
            f"и на акцию столько не дошло")


REVERSAL_NOTE_PCT = -20.0

# На сколько процентных пунктов скользящий год должен разойтись с концом
# окна, чтобы об этом стоило говорить. Поток к капиталу шумен, и разница в
# пару пунктов означает только то, что год не кончился ровно.
LTM_NOTE_SPREAD_PP = 10.0


def _ltm_cash_note(points, live) -> Optional[str]:
    """Скользящий год резко разошёлся с концом окна — сказать об этом вслух.

    В сам тест LTM не попадает, и это не упущение: скользящий год перекрывается
    с последним календарным примерно наполовину, и, положив оба в одну тройку,
    мы посчитали бы это полугодие дважды — ровно то, от чего сглаживание
    тройками и защищает. У Черкизово поток за июль 2025 — июнь 2026 оказался
    лучшим за всю историю, тогда как конец окна тянут вниз 2023 и 2024 годы;
    пустить туда LTM значило бы перевернуть вердикт с «не прошла» на «прошла»
    по одному неаудированному полугодию.

    Но и промолчать нельзя. Человек, читающий «−144%» рядом с рекордным
    потоком в таблице мультипликаторов, вправе узнать, что обе цифры верны и
    меряют разное, а не искать ошибку в расчёте.

    Сравниваются отдачи на капитал, а не величины на акцию: отдача от числа
    акций не зависит, и дробление её не сдвигает, тогда как поток на акцию
    пришлось бы приводить к одному масштабу вручную.
    """
    fresh = _live_fcf_to_equity(live)
    if fresh is None:
        return None
    direction = graham_growth(points, "fcf_per_share")
    if direction is None:
        direction = graham_growth(points, "fcf_per_share",
                                  GROWTH_SPAN_SHORT, CASH_SMOOTH_SHORT)
    if direction is None:
        return None
    by_year = {p.year: p for p in points}
    tail = [by_year[y].fcf_to_equity for y in direction.newer_years
            if y in by_year and by_year[y].fcf_to_equity is not None]
    if not tail:
        return None
    end = sum(float(v) for v in tail) / len(tail)
    if abs(fresh - end) < LTM_NOTE_SPREAD_PP:
        return None
    turn = "лучше" if fresh > end else "хуже"
    return (f"За скользящий год поток к капиталу {fresh:+.0f}% против {end:+.0f}% "
            f"в среднем по концу окна ({_years(direction.newer_years)}) — "
            f"заметно {turn}. Тест считает только по годовым точкам, и этот "
            f"разворот в него ещё не попал")


def _reversal_note(long_run: Optional[float], short_run: Optional[float],
                   what: str) -> Optional[str]:
    """Длинное окно растёт, короткое падает — сказать об этом вслух.

    Тесты гл. 14 меряют два конца десятилетия, и по построению они слепы к
    тому, что происходит внутри. У ФосАгро поток за десять лет вырос на 421%,
    а за пять упал на 65%: база 2016-2018 годов содержит убыточный по потоку
    2017-й (−56 ₽ на акцию), и на её фоне любое восстановление выглядит
    ростом, тогда как от пика 2022 года поток сложился вчетверо.

    Это не ошибка расчёта и не повод менять вердикт: у Грэма длинное окно
    выбрано сознательно, чтобы не шарахаться от циклов. Но человек, читающий
    «+421%» рядом с отрицательным потоком за последние двенадцать месяцев,
    имеет право узнать, что обе цифры верны и меряют разное.
    """
    if long_run is None or short_run is None:
        return None
    if long_run <= 0 or short_run > REVERSAL_NOTE_PCT:
        return None
    return (f"За пять лет {what} падает: {short_run:+.0f}% против {long_run:+.0f}% "
            f"за десять. Десятилетний тест сравнивает только концы окна и "
            f"разворот внутри него не видит")


def _join_notes(*parts: Optional[str]) -> Optional[str]:
    kept = [p for p in parts if p]
    return " · ".join(kept) if kept else None


def growth(points, is_lender: bool, live=None) -> Axis:
    """Рост: два конца десятилетия, каждый сглажен тройкой (гл. 14).

    Поток считается по тому же правилу, но с отступлением: у половины компаний
    свободного потока за десять лет просто нет — ряд начинается позже, чем
    прибыль. Тогда берётся пятилетний, и на это указано прямо, потому что
    «вырос за пять лет» и «вырос за десять» — разные утверждения, и молча
    подменять второе первым значит выдавать более слабое основание за
    исходное.
    """
    long_run, long_gap = _growth_with_gap(points, "eps")
    short_run, short_gap = _growth_with_gap(
        points, "eps", GROWTH_SPAN_SHORT, GROWTH_SMOOTH_SHORT)
    metrics = [
        Metric(
            key="earnings_growth", label="Прирост прибыли на акцию за 10 лет", unit="%",
            value=long_run, series=_series(points, "eps"), tone=_tone(long_run),
            suspect=_implausible(long_run, long_gap),
            note=_join_notes(
                _dilution_note(points, GROWTH_SPAN, 3),
                _reversal_note(long_run, short_run, "прибыль на акцию"),
            ),
        ),
        Metric(
            key="earnings_growth_short",
            label=f"Прирост прибыли на акцию за {GROWTH_YEARS_BACK_SHORT} лет", unit="%",
            value=short_run, tone=_tone(short_run),
            suspect=_implausible(short_run, short_gap),
            note=_join_notes(
                _short_growth_caveat(points),
                _dilution_note(points, GROWTH_SPAN_SHORT, GROWTH_SMOOTH_SHORT),
            ),
        ),
    ]
    if not is_lender:
        # Пятилетний поток считаем первым: он нужен не только своей строке, но
        # и длинной — чтобы та могла сказать, что внутри окна случился разворот.
        short_cash = _growth_percent(points, "fcf_per_share", GROWTH_SPAN_SHORT,
                                     CASH_SMOOTH_SHORT)
        cash_run = _growth_percent(points, "fcf_per_share")
        # Разворот, не попавший в годовые точки, касается обеих строк потока
        # одинаково: конец окна у них общий.
        ltm_note = _ltm_cash_note(points, live)
        span, note = GROWTH_SPAN, None
        if cash_run is None:
            # Сглаживание тройками в пять лет не помещается: тройка с каждого
            # конца требует шести лет. Берём пары — поток шумнее прибыли, и
            # одиночные годы по краям были бы слишком ненадёжной опорой.
            cash_run = _growth_percent(points, "fcf_per_share", GROWTH_SPAN_SHORT,
                                       CASH_SMOOTH_SHORT)
            span = GROWTH_SPAN_SHORT
            note = "Десяти лет потока в базе нет — взят пятилетний отрезок"
        metrics.append(Metric(
            key="cash_growth", label=f"Прирост FCF за {span} лет", unit="%",
            value=cash_run, series=_series(points, "fcf_per_share"),
            tone=_tone(cash_run), suspect=_implausible(cash_run),
            note=_join_notes(note, _reversal_note(cash_run, short_cash, "поток"),
                             ltm_note),
        ))
        # Пятилетний рост потока — на тот же отрезок, что и короткий тест по
        # прибыли, чтобы их можно было сравнивать между собой. Когда прибыль
        # обваливается на переписанной строке отчёта, а деньги нет, разницу
        # видно только при одинаковом окне. Сама величина посчитана выше.
        metrics.append(Metric(
            key="cash_growth_short",
            label=f"Прирост FCF за {GROWTH_YEARS_BACK_SHORT} лет", unit="%",
            value=short_cash, tone=_tone(short_cash),
            suspect=_implausible(short_cash),
            note=_join_notes("То же окно, что и у короткого теста по прибыли",
                             ltm_note),
        ))
    return Axis(
        key="growth", label="Рост",
        metrics=tuple(metrics), lead="earnings_growth",
    )


def _short_growth_caveat(points) -> str:
    """Почему пятилетнему тесту веры меньше — и насколько меньше именно тут.

    Слабость у него не в арифметике, а в том, куда попадают концы окна. На
    отчётности за 2025 год якорь «пять лет назад» — это 2020-й, ковидная яма,
    а середину накрывает 2022-й. Пара 2020–2021 усредняет обвал с рекордом, и
    у Газпрома тест из-за этого показывает рост там, где роста не было.

    Но вес у этой оговорки разный. Когда у компании есть десять лет, рядом
    стоит куда более крепкий тест гл. 14, и опираться надо на него. Когда
    истории меньше, пятилетний — единственное, что вообще есть, и отмахнуться
    от него значит остаться вовсе без суждения о росте.
    """
    history = len({y for y, _ in _series(points, "eps")})
    if history >= GROWTH_SPAN:
        return ("Окно накрывает 2020 и 2022 годы — оба ненормальные. "
                "Десятилетний тест на этой же компании надёжнее")
    return ("Окно накрывает 2020 и 2022 годы — оба ненормальные. "
            f"Но десяти лет истории нет ({history}), и по росту это "
            "единственная улика")


def _bank_fresh(ltm_bank: Optional[dict], name: str, series: tuple):
    """Величина за скользящий год, если она посчитана; иначе последний отчёт.

    До этой правки банковские показатели брались только из годовых отчётов,
    тогда как у соседних величин на той же строке стояло LTM. Два числа на
    разные даты, и пометка была лишь у одного: у Сбера доля проблемных в
    паспорте была 4,82% за 2025 год, а в таблице 5,42% за скользящий.
    """
    value = None if ltm_bank is None else ltm_bank.get(name)
    if value is not None:
        return float(value), LTM
    year = _year(series)
    return _last(series), (None if year is None else str(year))


def _bank_series(reports: dict) -> dict:
    """Банковские показатели по годам — по одному ряду на каждый.

    Считаются из тех же отчётов, что и всё остальное, тем же модулем, что
    наполняет таблицу мультипликаторов. Второй копии правил здесь нет
    намеренно: разойтись они сумеют, а заметить это будет нечем.
    """
    from app.services.analysis.bank_metrics import compute_bank_metrics

    names = ("cost_of_risk", "npl_ratio", "capital_adequacy_core",
             "loans_to_deposits", "net_interest_margin")
    out = {name: [] for name in names}
    for year, report in sorted(reports.items()):
        metrics = compute_bank_metrics(report)
        for name in names:
            value = getattr(metrics, name, None)
            if value is not None:
                out[name].append((year, float(value)))
    return {name: tuple(rows) for name, rows in out.items()}


def _peak(series: tuple) -> Optional[float]:
    """Худшее значение ряда. Для проблемных кредитов «худшее» — наибольшее."""
    return max((v for _, v in series), default=None)


def _mean(series: tuple, window: int = LEVEL_WINDOW) -> Optional[float]:
    """Средняя за последние `window` лет ряда.

    Нужна там, где показатель описывает **поведение**, а не запас: разовая
    экономия на издержках ничего не говорит о дисциплине, а низкая стоимость
    риска в хороший год бывает у всех — вопрос, какой она была в плохой.
    Достаточность капитала, наоборот, усреднять нельзя: это величина на дату.
    """
    recent = series[-window:]
    if not recent:
        return None
    return sum(v for _, v in recent) / len(recent)


def financial_position(mults: dict, reports: dict, is_lender: bool,
                       live=None, ltm_bank: Optional[dict] = None) -> Axis:
    """Финансовое положение: ликвидность и долг.

    У кредитной организации оборотного капитала в обычном смысле нет —
    депозиты клиентов обязательства по природе, и текущая ликвидность с
    отношением долга к капиталу теряют смысл целиком. Заменой служит
    достаточность капитала: то же по назначению, но посчитанное по правилам,
    которые к банку применимы.
    """
    if is_lender:
        bank = _bank_series(reports)
        adequacy = tuple(
            (year, float(report.capital_adequacy_ratio))
            for year, report in sorted(reports.items())
            if getattr(report, "capital_adequacy_ratio", None) is not None
        )
        core_series = bank["capital_adequacy_core"]
        npl_series = bank["npl_ratio"]
        ldr_series = bank["loans_to_deposits"]
        core, core_asof = _bank_fresh(ltm_bank, "capital_adequacy_core", core_series)
        npl, npl_asof = _bank_fresh(ltm_bank, "npl_ratio", npl_series)
        ldr, ldr_asof = _bank_fresh(ltm_bank, "loans_to_deposits", ldr_series)

        return Axis(
            key="financial", label="Финансовое положение",
            metrics=(
                Metric(key="capital_core", label="Достаточность основного капитала",
                       unit="%", value=core, series=core_series, asof=core_asof,
                       note="Н1.1 / CET1 — поглощает убытки первым. "
                            "Величина на дату: средняя достаточность бессмысленна"),
                Metric(key="capital_adequacy", label="Достаточность капитала, Н1.0",
                       unit="%", value=_last(adequacy), series=adequacy,
                       asof=(None if _year(adequacy) is None
                             else str(_year(adequacy)))),
                Metric(key="npl_ratio", label="Проблемные кредиты", unit="%",
                       value=npl, series=npl_series, asof=npl_asof,
                       average=_peak(npl_series),
                       note="Рядом со средней стоит пик за историю: запас "
                            "смотрят сегодня, но знать надо, что бывало"),
                Metric(key="loans_to_deposits", label="Кредиты к средствам клиентов",
                       unit="%", value=ldr, series=ldr_series, asof=ldr_asof,
                       note="Выше 100% — разница финансируется рынком, "
                            "то есть дороже и капризнее депозитов"),
            ),
            lead="capital_core",
            note="Ликвидность и долг к капиталу к кредитной организации неприменимы",
        )

    liquidity = _mult_series(mults, "current_ratio")
    leverage = _mult_series(mults, "debt_to_equity")
    coverage = _mult_series(mults, "net_debt_to_fcf")

    cr, cr_asof = _fresh(live, "current_ratio", _last(liquidity), _year(liquidity))
    de, de_asof = _fresh(live, "debt_to_equity", _last(leverage), _year(leverage))
    nd, nd_asof = _fresh(live, "net_debt_to_fcf", _last(coverage), _year(coverage))
    debt_tone, debt_note = _debt_tone(_net_debt(mults, live), nd)

    return Axis(
        key="financial", label="Финансовое положение",
        metrics=(
            Metric(key="current_ratio", label="Текущая ликвидность", unit="×",
                   value=cr, series=liquidity, asof=cr_asof),
            Metric(key="debt_to_equity", label="Долг к капиталу", unit="×",
                   value=de, series=leverage, asof=de_asof),
            Metric(key="net_debt_to_fcf", label="Чистый долг к FCF", unit="×",
                   value=nd, series=coverage, asof=nd_asof,
                   tone=debt_tone, note=debt_note),
        ),
        lead="current_ratio",
    )


def _year(series: tuple) -> Optional[int]:
    return series[-1][0] if series else None


def _net_debt(mults: dict, live) -> Optional[float]:
    """Сам чистый долг, а не отношение: цвет отношения решается по нему."""
    value = _live(live, "net_debt")
    if value is None and mults:
        last = mults.get(max(mults))
        value = None if last is None else getattr(last, "net_debt", None)
    return None if value is None else float(value)


def _debt_tone(net_debt: Optional[float], ratio: Optional[float]):
    """Цвет отношения «чистый долг к потоку» — по знаку долга, не отношения.

    Минус в этой дроби получается двумя противоположными способами, и красить
    их одинаково — прямая ошибка. У Лукойла чистый долг −379 млрд: денег
    больше, чем займов, отношение −0,46, и это хорошо. У Аэрофлота долг
    +537 млрд при потоке −128 млрд, отношение −4,19, и означает оно, что долг
    не гасится вовсе. Смотреть надо на числитель.

    Положительное отношение остаётся без цвета: «два года потока на погашение»
    и «двенадцать» — разница в пороге, а не в знаке, и порог здесь не наш.
    """
    if ratio is None or net_debt is None:
        return None, "Сколько лет свободного потока нужно, чтобы погасить чистый долг"
    if net_debt < 0:
        return "good", "Чистый долг отрицателен: денег больше, чем займов"
    if ratio < 0:
        return "bad", ("Отношение отрицательно из-за убытка по потоку, а не "
                       "из-за отсутствия долга — долг не гасится вовсе")
    return None, "Сколько лет свободного потока нужно, чтобы погасить чистый долг"


def dividends(points, mults: dict, live=None) -> Axis:
    """Дивиденды: непрерывная серия и доходность в динамике.

    Двадцать лет из гл. 14 на российском рынке проверить нечем — истории
    столько нет ни у кого. Поэтому рядом с длиной серии всегда стоит число
    доступных лет: «18 из 18» и «12 из 18» — разные утверждения, и сводить их
    к одной цифре значит скрыть, чего мы не знаем.
    """
    streak, paid, available = _dividend_history(points)
    yields = _mult_series(mults, "dividend_yield")
    recent = yields[-LEVEL_WINDOW:]
    # Доходность считается от цены, а цена меняется каждый день: годовая
    # величина устаревает быстрее всех остальных на этой оси.
    yield_now, yield_asof = _fresh(live, "dividend_yield", _last(yields), _year(yields))
    return Axis(
        key="dividends", label="Дивиденды",
        metrics=(
            Metric(key="streak", label="Лет подряд с выплатой", unit="лет",
                   value=float(streak), of=float(available),
                   tone=_tone_full(float(streak), float(available))),
            Metric(key="paid_years", label="Лет с выплатой за всю историю",
                   unit="лет", value=float(paid), of=float(available),
                   tone=_tone_full(float(paid), float(available)),
                   note="Не подряд: показывает, платила ли вообще"),
            Metric(key="dividend_yield", label="Дивидендная доходность", unit="%",
                   value=yield_now, series=yields, asof=yield_asof,
                   average=(sum(v for _, v in recent) / len(recent)) if recent else None),
        ),
        lead="streak",
    )


def price_level(points, mults: dict, live=None) -> Axis:
    """Динамика цен: P/E по средней за три года, P/B и их произведение.

    Знаменатель — средняя за три года и по отчётной прибыли: то же правило,
    что и для всех многолетних средних. **Числитель — сегодняшняя цена.** Это
    не половинчатость, а сам смысл критерия: Грэм спрашивает, дорого ли
    покупать *сейчас* относительно того, что компания зарабатывает *обычно*.
    Взять цену на конец отчётного года значит проверять сделку, которой уже
    нет: у Лукойла 31.12.2025 акция стоила 5 880 ₽ против сегодняшних 4 554 ₽,
    и P/E по старой цене завышен почти на треть.

    Произведение — критерий 7 гл. 14: Грэм связывает две величины намеренно,
    «чем больше одна, тем меньше другая», и раздельные пороги эту связь теряют.
    """
    average_earnings = window_average(points, "eps", PRICE_WINDOW)
    annual = _series(points, "price_normalized")
    price, price_asof = _fresh(live, "price_used", _last(annual), _year(annual))

    pe = None
    if average_earnings is not None and average_earnings.value > 0 and price:
        pe = price / average_earnings.value

    pb_series = _mult_series(mults, "pb_ratio")
    pb, pb_asof = _fresh(live, "pb_ratio", _last(pb_series), _year(pb_series))
    product = None if pe is None or pb is None else pe * pb
    tangible, tangible_note = _tangible_pb(mults, live, pb)

    window = (None if average_earnings is None
              else f"средняя прибыль за {average_earnings.years_used} лет")

    return Axis(
        key="price", label="Динамика цен",
        metrics=(
            Metric(key="pe_average", label=f"P/E по средней за {PRICE_WINDOW} года",
                   unit="×", value=pe, asof=price_asof, note=window),
            Metric(key="pb", label="P/B", unit="×", value=pb,
                   series=pb_series, asof=pb_asof),
            Metric(key="pb_tangible", label="P/B по материальному капиталу",
                   unit="×", value=tangible, asof=pb_asof, note=tangible_note),
            Metric(key="pe_pb", label="Произведение P/E × P/B", unit="×",
                   value=product, asof=price_asof),
        ),
        lead="pe_average",
    )


def _tangible_pb(mults: dict, live, pb: Optional[float]):
    """Цена к капиталу за вычетом гудвила — то, что требует гл. 15.

    Гудвил не производственный актив, а след цены, заплаченной за прошлые
    покупки: пока сделка себя оправдывает, он стоит в балансе, а когда
    перестаёт — списывается разом. Охотнику за дешевизной обеспечение нужно
    твёрдое, поэтому Грэм в гл. 15 меряет цену «чистой стоимостью
    материальных активов», тогда как защитному инвестору в гл. 14 хватает
    обычной балансовой. Это не противоречие у него, а разные задачи.

    Вычитается **только гудвил**, а не все нематериальные активы. Буквальное
    «вон всё нематериальное» в 2026 году было бы не консерватизмом, а другой
    ошибкой: купленные лицензии и софт — настоящие средства производства.

    Когда гудвила нет, материальный капитал равен балансовому, и величина
    просто повторяет P/B. Отказываться считать здесь нечего.
    """
    series = _mult_series(mults, "pb_tangible")
    value = _live(live, "pb_tangible")
    if value is None:
        value = _last(series)
    if value is None:
        return pb, "Гудвила нет — материальный капитал равен балансовому"
    return float(value), "Из капитала вычтен гудвил"


def size(mults: dict, live=None) -> Axis:
    """Размер. Защитному инвестору Грэм ставит порог, активному — снял."""
    revenue = _mult_series(mults, "ltm_revenue")
    value, asof = _fresh(live, "ltm_revenue", _last(revenue), _year(revenue))
    return Axis(
        key="size", label="Размер",
        metrics=(Metric(key="revenue", label="Выручка", unit="млн ₽",
                        value=value, series=revenue, asof=asof),),
        lead="revenue",
    )


# ─── Сборка ─────────────────────────────────────────────────────────────────

# Порядок — как в гл. 13, размер добавлен из гл. 14 в конец.
AXIS_ORDER = (
    "profitability", "stability", "growth",
    "financial", "dividends", "price", "size",
)


def build(points, mults: dict, reports: dict, is_lender: bool = False,
          live=None, ltm_bank: Optional[dict] = None) -> list:
    """Семь осей по готовому ряду. Порогов не накладывает.

    `live` — свежий срез кэша за последние двенадцать месяцев. Из него берутся
    величины «сейчас»; средние и ряды остаются календарными. Подмешивать
    скользящий год в среднюю нельзя: он перекрывается с последним календарным,
    и год посчитался бы дважды.
    """
    return [
        profitability(points, mults, reports, is_lender, live),
        stability(points, is_lender, reports, ltm_bank),
        growth(points, is_lender, live),
        financial_position(mults, reports, is_lender, live, ltm_bank),
        dividends(points, mults, live),
        price_level(points, mults, live),
        size(mults, live),
    ]


def load(db, company) -> list:
    """То же, но само достаёт ряд из базы.

    Годовые срезы кэша мультипликаторов уже переведены в рубли и посчитаны от
    тех же отчётов, по которым строится ряд прибыли, поэтому баланс и лестницы
    берутся из одного места и разъехаться не могут.

    Годовые отчёты отбираются явно: словарь здесь строится по году, и
    квартальный срез, попав в него, молча вытеснил бы годовой — ошибка, которую
    было бы видно только по странным величинам.
    """
    from app.models.financial_report import FinancialReport
    from app.models.multiplier import Multiplier

    points = load_points(db, company.id)
    rows = (
        db.query(Multiplier, FinancialReport)
        .join(FinancialReport, Multiplier.report_id == FinancialReport.id)
        .filter(
            Multiplier.company_id == company.id,
            Multiplier.type == "report_based",
            FinancialReport.period_type == "ANNUAL",
        )
        .order_by(Multiplier.date)
        .all()
    )
    mults = {mult.date.year: mult for mult, _ in rows}
    reports = {mult.date.year: report for mult, report in rows}

    # Свежий срез: тот же кэш, но за последние двенадцать месяцев и по
    # сегодняшней цене. Именно он отвечает на вопрос «сколько компания
    # зарабатывает и сколько стоит сейчас».
    live = (
        db.query(Multiplier)
        .filter(Multiplier.company_id == company.id, Multiplier.type == "current")
        .order_by(Multiplier.date.desc())
        .first()
    )

    is_lender = str(getattr(company, "company_type", "")).upper().endswith("LENDER")

    # Банковские показатели за скользящий год. Считает их тот же сервис, что
    # наполняет строку LTM в таблице мультипликаторов, — второй копии правил
    # здесь нет намеренно: разойтись они сумеют, а заметить будет нечем.
    ltm_bank = None
    if is_lender:
        from app.services.analysis.multiplier_service import compute_ltm_bank_metrics
        ltm_bank = compute_ltm_bank_metrics(db, company.id)

    return build(points, mults, reports, is_lender, live, ltm_bank)


def as_dict(axes: list) -> dict:
    """Оси в порядке главы 13, ключом — их код."""
    return {axis.key: axis.as_dict() for axis in axes}
