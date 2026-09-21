"""Экран Грэма: пороги поверх осей.

Разделение труда здесь такое:

    screen_axes      что измеряем — величины и ряды, без единого порога
    sector_profiles  чем меряем в этой отрасли — уже существующие полосы
    screen           что из этого следует — свод книжных критериев и вердикт

Наборов критериев два, и они не смешиваются. Защитный инвестор (гл. 14,
с. 371–372) получает семь требований, каждое строгое. Активный (гл. 15,
с. 419) — свои, заметно мягче: Грэм прямо снимает требование к размеру,
опускает ликвидность до 1,5, сокращает горизонт безубыточности с десяти лет до
пяти и заменяет тест роста на простое сравнение с пятилетней давностью. Между
«20 лет непрерывных дивидендов» и «платит сейчас» середины не существует,
поэтому объединять списки в один нельзя — можно только выбрать, каким мерить.

**Активный свод мягче не во всём.** Он мягче по качеству — ликвидность,
история, дивиденды — и **строже по цене**: защитному инвестору Грэм разрешает
P/B до 1,5, активному только до 1,2. Противоречия здесь нет, это две разные
сделки. Защитный покупает хорошую компанию по справедливой цене и платит за
надёжность; активный покупает дешёвую и требует скидки, потому что больше ему
опереться не на что. Компания, проходящая по цене у защитного и не проходящая
у активного, — обычный случай, а не сбой расчёта.

**Отраслевая поправка.** Пороги Грэма выведены для промышленных компаний США
1930–40-х годов, и часть из них на российском рынке 2020-х даёт ложный сигнал
чаще, чем верный: текущая ликвидность 0,67 у продуктовой сети — это способ
торговать, а не риск. Поэтому там, где `sector_profiles` задаёт для отрасли
свою полосу, применяется она, а книжное значение остаётся рядом и видно.
Каждый вердикт несёт оба числа и признак, что порог сдвинут: скрытая поправка
превращает экран в гадание, потому что провал уже нельзя отличить от чужой
мерки.

**Чего экран не делает.** Он не складывает оси в балл и не сортирует по нему.
Грэм требует прохождения *всех* критериев, а не суммы очков: компания с шестью
пятёрками и одним нулём у него не проходит, и усреднение это скрыло бы. Свод
поэтому считает пройденные и непройденные оси, но общего числа не выводит.

**Неизмеримое — не провал.** Ось без данных и ось, неприменимая к отрасли,
отделены от провала намеренно. У банка нет текущей ликвидности не потому, что
он плох, а потому, что депозиты клиентов — обязательства по природе. Считать
это непрохождением значит завалить весь сектор устройством формулы.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.services.analysis import screen_axes
from app.services.analysis.sector_profiles import (
    GRAHAM_DEFAULT,
    SectorProfile,
    resolve_profile,
)

# ─── Числа, которых в книге нет в готовом виде ──────────────────────────────

# Грэм требовал от промышленной компании не менее 100 млн $ годовой выручки
# (гл. 14, с. 371, цены 1971 года). Доллар с тех пор подешевел примерно
# в восемь раз, что даёт около 800 млн $, или 65 млрд ₽ по нынешнему курсу.
# Берём 50 млрд — ниже пересчёта, потому что российский рынок меньше
# американского на порядок, и планка «как в США» отсекла бы почти всё.
# Величина наша, не книжная, и помечена как суждение.
MIN_REVENUE = 50_000.0  # млн ₽

# Гл. 14, критерий 3: непрерывные выплаты **не менее 20 лет**. На российском
# рынке столько истории нет ни у кого — в базе максимум 18 лет, и порог в 20
# отсекал бы всех по причине, к компаниям отношения не имеющей. Взято 10:
# полный цикл плюс запас. Отступление от книги, и оно названо.
DIVIDEND_YEARS = 10

# Гл. 14, критерий 5: прирост не менее трети за десять лет.
GROWTH_THRESHOLD = 100 / 3

# Гл. 14, критерий 7: «произведение множителей не должно превышать 22,5».
PE_PB_PRODUCT = 22.5

# Гл. 15, с. 419: активному инвестору хватает половины книжной ликвидности.
ENTERPRISING_CURRENT_RATIO = 1.5

STANDARDS = ("defensive", "enterprising")
STANDARD_LABELS = {
    "defensive": "Защитный инвестор (гл. 14)",
    "enterprising": "Активный инвестор (гл. 15)",
}

# Ключ полосы в `sector_profiles` для тех величин, у которых он есть. Без
# записи здесь порог остаётся книжным при любой отрасли.
PROFILE_KEYS = {
    "current_ratio": "cr",
    "debt_to_equity": "de",
    "pe_average": "pe",
    "pb": "pb",
    # Материальный капитал меряется той же отраслевой полосой, что и
    # балансовый: отрасль говорит, во сколько раз здесь принято платить за
    # капитал, и вычтенный гудвил этого не меняет.
    "pb_tangible": "pb",
    "roe": "roe",
    "dividend_yield": "dy",
    "cost_to_income_average": "cir",
}

# Статусы вердикта. Три последних — не провал, и складывать их с ним нельзя.
PASS = "pass"
FAIL = "fail"
UNKNOWN = "unknown"          # величины нет в базе
NOT_APPLICABLE = "n/a"       # отрасли эта мерка не подходит


@dataclass(frozen=True)
class Rule:
    """Одно требование: к какой величине, в какую сторону и откуда взято.

    `mode` — как сравнивать:
        min   величина не ниже порога
        max   величина не выше порога
        all   все годы окна чистые (`value == of`)
        most  чистых лет большинство (`value * 2 >= of`)
    """

    axis: str
    metric: str
    mode: str
    threshold: Optional[float]
    source: str
    ours: bool = False       # порог наш, а не книжный
    note: Optional[str] = None
    # Запасная величина той же оси: если основная не прошла, а эта прошла,
    # критерий засчитывается, и в вердикте сказано, что вытянула она. Нужна
    # там, где прибыль и деньги расходятся: у Лукойла отчётная прибыль за
    # 2025 год записана по продолжающейся деятельности и упала вчетверо, а
    # свободный поток за ту же пятилетку почти не изменился. Считать компанию
    # сжимающейся по переписанной строке отчёта, когда деньги говорят другое,
    # значит доверять форме отчёта больше, чем кассе.
    alt: Optional[str] = None
    # Улика слабая: критерий считается, но опираться на него в одиночку
    # нельзя. Ставится там, где ненадёжна не арифметика, а сама постановка
    # вопроса — так у пятилетнего теста роста, чьё окно на российских данных
    # неизбежно накрывает 2020 и 2022 годы. Пояснение берётся у самой
    # величины: оно зависит от компании, а не от правила.
    weak: bool = False
    # Порог берётся по краю «плохо», а не «хорошо».
    #
    # У книжных критериев край один: Грэм назвал число, и оно и есть граница.
    # У наших — три уровня, потому что они пришли из отраслевых полос, где
    # есть и «хорошо», и «приемлемо». Судить по краю «хорошо» значит объявлять
    # провалом всё приемлемое: у Сбера стоимость риска 1,03 против «хорошо»
    # 1,0 — мимо на три сотых, при том что таблица мультипликаторов красит
    # это значение жёлтым, то есть приемлемым.
    #
    # Расхождение между таблицей и паспортом отсюда и бралось. С этим флагом
    # красное в таблице означает провал в паспорте, и наоборот.
    lenient: bool = False

    def holds(self, value: Optional[float], of: Optional[float]) -> Optional[bool]:
        if value is None:
            return None
        if self.mode == "all":
            return None if of is None else value >= of
        if self.mode == "most":
            return None if of is None else value * 2 >= of
        if self.threshold is None:
            return None
        if self.mode == "min":
            return value >= self.threshold
        return value <= self.threshold

    def text(self, threshold: Optional[float] = None) -> str:
        limit = self.threshold if threshold is None else threshold
        if self.mode == "all":
            return "без единого убытка"
        if self.mode == "most":
            return "большинство лет"
        if limit is None:
            # Порога в книге нет вовсе — так стоит рентабельность. Прочерк
            # прочитался бы как «не проверяем», а проверяем мы её отраслевой
            # полосой, и сказать это надо прямо.
            return "по профилю" if self.ours else "—"
        return f"{'≥' if self.mode == 'min' else '≤'} {_readable(limit)}"


def _readable(value: float) -> str:
    """Порог в человеческом виде: 33⅓ не показывают как 33.3333, а 50000 — как
    50000. Разрядность зависит от величины: у порога 0,96 десятая доля — это
    четверть его самого, и округление до единицы меняет смысл, а у 33,3 —
    сотая часть, и она не значит ничего."""
    digits = 2 if abs(value) < 10 else 1
    rounded = round(value, digits)
    if rounded == int(rounded):
        return f"{int(rounded):,}".replace(",", " ")
    return f"{rounded:g}"


# ─── Своды критериев ────────────────────────────────────────────────────────

# Свободный поток — наше добавление к обоим сводам. У Грэма его нет вовсе:
# отчёта о движении денежных средств в его виде в 1949 году не существовало, и
# судил он по прибыли. Но прибыль и деньги расходятся годами: у Позитива
# прибыль ровная, а поток отрицателен, и свод, который этого не видит, выдаёт
# такую компанию за устойчивую.
#
# Пороги здесь мягче, чем по прибыли, и намеренно. Требовать десять лет подряд
# с положительным потоком нельзя: у любого, кто строит, капекс идёт волнами, и
# отрицательный поток в год стройки — не убыток, а вложение. Поэтому спрашиваем
# лишь про большинство лет и про то, чтобы поток за окно не сжимался.
CASH_RULES = (
    Rule("stability", "cash_positive_years", "most", None,
         "наше добавление · у Грэма потока нет", ours=True,
         note="Большинство лет с положительным потоком; сплошной ряд требовать нельзя"),
    Rule("growth", "cash_growth", "min", 0.0,
         "наше добавление · у Грэма потока нет", ours=True,
         note="Поток за окно не должен сжиматься"),
)

# Кредитная организация меряется своим. У Грэма банков в списках нет вовсе —
# в 1949 и 1972 годах они были предметом отдельного разбора, а не защитного
# отбора. Поэтому все пороги здесь наши, взяты из `bank_metrics`, где уже
# сложены полосы, и помечены как суждение.
#
# Разделение то же, что и везде: **среднее там, где показатель описывает
# поведение, точка — где он описывает запас.** Издержки к доходам и стоимость
# риска судятся по средней за семь лет: разовая экономия ничего не доказывает,
# а низкая стоимость риска в хороший год бывает у всех. Достаточность капитала
# и доля проблемных кредитов — величины на дату, усреднять их бессмысленно.
#
# Правила стоят в обоих сводах. Небанк получит по ним «не применяется»
# автоматически: у его осей таких подметрик нет — ровно так же, как банк
# получает «не применяется» по свободному потоку.
LENDER_RULES = (
    Rule("profitability", "cost_to_income_average", "max", None,
         "наше добавление · у Грэма банков нет", ours=True, lenient=True,
         note="Судим по средней: издержки описывают поведение, а не запас"),
    Rule("stability", "cost_of_risk_average", "max", 2.0,
         "наше добавление · норма цикла", ours=True, lenient=True,
         note="Сколько портфеля банк списывает ежегодно. В хороший год низкая "
              "у всех — потому и средняя за цикл"),
    Rule("financial", "capital_core", "min", 8.0,
         "наше добавление · Н1.1", ours=True, lenient=True,
         note="Основной капитал поглощает убытки первым. Величина на дату"),
    Rule("financial", "npl_ratio", "max", 8.0,
         "наше добавление · качество портфеля", ours=True, lenient=True),
)

DEFENSIVE = (
    Rule("size", "revenue", "min", MIN_REVENUE,
         "гл. 14, критерий 1", ours=True,
         note="Пересчёт книжных 100 млн $ 1971 года — величина наша"),
    Rule("financial", "current_ratio", "min", 2.0,
         "гл. 14, критерий 2"),
    Rule("stability", "profitable_years", "all", None,
         f"гл. 14, критерий 4 — {screen_axes.STABILITY_SPAN} лет"),
    Rule("growth", "earnings_growth", "min", GROWTH_THRESHOLD,
         "гл. 14, критерий 5"),
    Rule("dividends", "streak", "min", float(DIVIDEND_YEARS),
         "гл. 14, критерий 3", ours=True,
         note="У Грэма 20 лет; столько истории на российском рынке нет"),
    Rule("price", "pe_average", "max", 15.0,
         "гл. 14, критерий 6"),
    Rule("price", "pb", "max", 1.5,
         "гл. 14, критерий 7"),
    Rule("price", "pe_pb", "max", PE_PB_PRODUCT,
         "гл. 14, критерий 7 — произведение"),
    *CASH_RULES,
    *LENDER_RULES,
    # Короткое окно по потоку — наше добавление сверх CASH_RULES, и только в
    # защитном своде: в активном та же величина уже стоит запасной к прибыли.
    #
    # У Грэма коротких окон в гл. 14 нет вовсе, и это осознанно: длинное окно
    # выбрано, чтобы не шарахаться от циклов. Но оно сравнивает только два
    # конца и разворот внутри не видит. У ФосАгро поток за десять лет вырос на
    # 421% при базе 2016-2018 годов, куда попал убыточный по потоку 2017-й, а
    # за пять лет упал на 65% и от пика 2022 года сложился вчетверо. Свод,
    # который этого не замечает, ставит её рядом с теми, у кого поток не
    # сжимался.
    #
    # Проверено по базе: с прохода не снимается никто — единственный, кто
    # сейчас проходит защитный свод, ЛУКОЙЛ, держит +68% за пять лет. Правило
    # добавляет различение в середине списка, а не рубит верх.
    Rule("growth", "cash_growth_short", "min", 0.0,
         "наше добавление · у Грэма коротких окон нет", ours=True,
         note="Поток за последние пять лет не должен сжиматься"),
)

ENTERPRISING = (
    Rule("size", "revenue", "min", None,
         "гл. 15 — требование снято",
         note="Активному инвестору Грэм размер не ограничивает"),
    Rule("financial", "current_ratio", "min", ENTERPRISING_CURRENT_RATIO,
         "гл. 15, с. 419"),
    Rule("stability", "profitable_years_short", "all", None,
         f"гл. 15 — {screen_axes.STABILITY_SPAN_SHORT} лет без убытка"),
    Rule("growth", "earnings_growth_short", "min", 0.0,
         "гл. 15 — выше, чем пять лет назад",
         alt="cash_growth_short", weak=True),
    Rule("dividends", "streak", "min", 1.0,
         "гл. 15 — платит сейчас"),
    # По цене активный свод строже защитного, и это у Грэма нарочно: защитный
    # инвестор берёт хорошее по справедливой цене, активный — дешёвое, и
    # скидку требует больше. Своего порога по P/E активному он не назначает,
    # поэтому здесь стоит тот же, что в гл. 14.
    Rule("price", "pe_average", "max", 15.0,
         "гл. 14, критерий 6"),
    Rule("price", "pb_tangible", "max", 1.2,
         "гл. 15 — не выше 120% чистых материальных активов"),
    *CASH_RULES,
    *LENDER_RULES,
)

RULES = {"defensive": DEFENSIVE, "enterprising": ENTERPRISING}

# Рентабельность у Грэма порога не имеет ни в одном списке — она ось описания.
# В проекте на неё опирается устойчивый рост в множителе рынка, поэтому порог
# всё же нужен, и берётся он целиком из отраслевого профиля.
PROFITABILITY_RULE = Rule(
    "profitability", "roe", "min", None,
    "порога у Грэма нет", ours=True,
    note="Берётся из отраслевого профиля",
)


# ─── Вердикт ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    """Одна ось против одного требования — с обоими порогами напоказ."""

    axis: str
    label: str
    metric: str
    metric_label: str
    value: Optional[float]
    unit: str
    of: Optional[float]
    status: str
    rule: Rule
    applied: Optional[float]      # порог, который применили
    book: Optional[float]         # что стоит в книге
    reason: Optional[str] = None
    # Оговорка к засчитанному критерию: он посчитан, но опираться на него в
    # одиночку нельзя. Не то же, что `reason`: там сказано, почему вердикт
    # такой, здесь — почему ему верить не до конца.
    caveat: Optional[str] = None
    # Величина есть, но верить ей нельзя. Отличается от «нет данных» тем, что
    # мы знаем, чего не хватает: не строки в базе, а осмысленного знаменателя.
    # Читателю разница существенна — «не нашли» и «нашли, но это не то».
    distorted: bool = False
    # Прошла, но только по мягкому краю. Полоса отрасли знает три уровня —
    # «хорошо», «приемлемо», «плохо», — а вердикт двоичен, и без этой пометки
    # приемлемое красилось бы зелёным. У Сбера доля проблемных 7,7% при
    # «хорошо» 4 и «плохо» 8: таблица мультипликаторов пишет жёлтым, паспорт
    # писал зелёным, и одно и то же число выглядело по-разному в двух местах.
    marginal: bool = False

    @property
    def adjusted(self) -> bool:
        """Сдвинут ли порог отраслью относительно книжного."""
        return (self.applied is not None and self.book is not None
                and self.applied != self.book)

    @property
    def counts(self) -> bool:
        return self.status in (PASS, FAIL)

    @property
    def shortfall(self) -> Optional[float]:
        """Насколько провалена планка — в долях самой планки.

        Вердикт у Грэма двоичный, и таким остаётся: свод требует всех
        критериев сразу, «почти прошла» у него не засчитывается. Но двоичным
        обязан быть ИТОГ, а не то, что видит человек. Татнефть с отдачей 12%
        и Роснефть с 3,2% проваливают один и тот же порог 15%, и рисовать их
        одинаковым крестиком — терять четырёхкратную разницу, которая для
        выбора между ними и есть главное.

        0,20 значит «не дотянула пятую часть порога», 0,78 — «провалила почти
        целиком». Для `max`-правил считается в другую сторону: превышение.

        Счётные правила (`all`, `most`) мерятся долей от требуемого числа лет:
        девять чистых лет из десяти и два из десяти — это 0,1 против 0,8, и
        уравнивать их значит терять ровно ту разницу, ради которой критерий и
        читают. У `most` планка — половина окна, от неё и считается.
        """
        if self.status != FAIL or self.value is None:
            return None

        if self.rule.mode == "all":
            limit = self.of
        elif self.rule.mode == "most":
            limit = None if self.of is None else self.of / 2.0
        else:
            limit = self.applied

        if not limit:
            return None

        gap = (self.value - limit) if self.rule.mode == "max" else (limit - self.value)
        return round(gap / abs(limit), 4)

    def as_dict(self) -> dict:
        return {
            "axis": self.axis,
            "label": self.label,
            "metric": self.metric,
            "metric_label": self.metric_label,
            "value": None if self.value is None else round(self.value, 4),
            "unit": self.unit,
            "of": self.of,
            "status": self.status,
            "applied": self.applied,
            "book": self.book,
            "adjusted": self.adjusted,
            "text": self.rule.text(self.applied),
            "book_text": self.rule.text(self.book),
            "source": self.rule.source,
            "ours": self.rule.ours,
            "note": self.reason or self.rule.note,
            "caveat": self.caveat,
            "distorted": self.distorted,
            "marginal": self.marginal,
            "shortfall": self.shortfall,
        }


@dataclass(frozen=True)
class Screen:
    """Свод по компании. Балла не выводит — Грэм требует всех критериев сразу."""

    ticker: str
    standard: str
    profile: SectorProfile
    verdicts: tuple

    @property
    def checkable(self) -> tuple:
        return tuple(v for v in self.verdicts if v.counts)

    @property
    def passed(self) -> int:
        return sum(1 for v in self.checkable if v.status == PASS)

    @property
    def failed(self) -> tuple:
        return tuple(v for v in self.checkable if v.status == FAIL)

    @property
    def unknown(self) -> tuple:
        return tuple(v for v in self.verdicts if v.status == UNKNOWN)

    @property
    def complete(self) -> bool:
        """Не осталось ли осей, которые не удалось проверить.

        Пробел — только `unknown`, то есть нехватка данных. Неприменимость —
        решённое состояние, а не дыра: у банка нет текущей ликвидности по
        устройству бизнеса, и требовать её значит не «мы чего-то не знаем»,
        а «мы меряем не тем».
        """
        return not self.unknown

    @property
    def clears(self) -> bool:
        """Прошла ли компания. Непроверенная ось — не прохождение."""
        return bool(self.checkable) and not self.failed and self.complete

    def as_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "standard": self.standard,
            "standard_label": STANDARD_LABELS.get(self.standard, self.standard),
            "profile": {"key": self.profile.key, "label": self.profile.label},
            "passed": self.passed,
            "checked": len(self.checkable),
            "total": len(self.verdicts),
            "complete": self.complete,
            "clears": self.clears,
            "failed": [v.metric for v in self.failed],
            "unknown": [v.metric for v in self.unknown],
            "verdicts": [v.as_dict() for v in self.verdicts],
        }


# ─── Применение ─────────────────────────────────────────────────────────────

# Банковские показатели своих полос в отраслевом профиле не имеют: их уровни
# живут в `bank_metrics`, откуда их берёт и таблица мультипликаторов. Ключ
# нужен, чтобы спросить там тот же край «хорошо».
BANK_BANDS = {
    "cost_of_risk_average": "cost_of_risk",
    "capital_core": "capital_adequacy_core",
    "npl_ratio": "npl_ratio",
}


def _strict_edge(rule: Rule, profile: SectorProfile) -> Optional[float]:
    """Край «хорошо» — тот, по которому красит таблица мультипликаторов."""
    bank_key = BANK_BANDS.get(rule.metric)
    if bank_key is not None:
        from app.services.analysis.bank_metrics import _BANDS
        band = _BANDS.get(bank_key)
        return None if band is None else float(band[0])

    key = PROFILE_KEYS.get(rule.metric)
    band = None if key is None else profile.bands.get(key)
    if band is None or not band.applicable or band.good is None:
        return None
    return float(band.good)


def _threshold(rule: Rule, profile: SectorProfile):
    """Порог с отраслевой поправкой: (применённый, книжный, неприменимо ли).

    Поправка **относительная**, а не подстановка. Профиль `industrial` — это в
    точности числа Грэма (ликвидность 2, P/E 15, P/B 1,5), поэтому остальные
    профили можно читать как «во сколько раз эта отрасль отличается от
    промышленной», и на столько же двигать книжный порог выбранного свода.

    Подстановка абсолютного значения ломала бы сам выбор свода: активный
    инвестор, которому Грэм разрешает ликвидность 1,5, получал бы от
    промышленного профиля 2,0 — то есть строгость **выше** книжной там, где
    книга её понижает. Отрасль и строгость должны складываться, а не спорить.

    Пометка `applicable=False` — отдельный случай: она означает не «порог
    другой», а «этой меркой отрасль не мерят».
    """
    key = PROFILE_KEYS.get(rule.metric)
    band = None if key is None else profile.bands.get(key)
    if band is None:
        return rule.threshold, rule.threshold, False
    if not band.applicable:
        return None, rule.threshold, True
    edge = band.warn if rule.lenient and band.warn is not None else band.good
    if edge is None:
        return rule.threshold, rule.threshold, False
    if rule.threshold is None:
        # У правила своего порога нет — так стоит рентабельность, которой
        # у Грэма нет вовсе. Отраслевое значение тогда берётся как есть.
        return float(edge), None, False

    base = GRAHAM_DEFAULT.bands.get(key)
    if base is None or not base.good:
        return rule.threshold, rule.threshold, False
    ratio = float(edge) / float(base.good)
    return round(rule.threshold * ratio, 4), rule.threshold, False


def _alternate(rule: Rule, axis, applied: Optional[float]) -> Optional[str]:
    """Прошла ли запасная величина там, где основная не прошла.

    Возвращает объяснение для вердикта или None. Объяснение обязательно:
    засчитать критерий по другой величине и промолчать об этом значит выдать
    проверку прибыли за то, чем она не была.
    """
    if rule.alt is None or axis is None:
        return None
    spare = axis.metric(rule.alt)
    if spare is None or spare.value is None or spare.suspect:
        return None
    holds = Rule(rule.axis, rule.alt, rule.mode, applied,
                 rule.source, rule.ours).holds(spare.value, spare.of)
    if not holds:
        return None
    return f"По прибыли не прошла, засчитано по деньгам: {spare.label.lower()}"


def _judge(rule: Rule, axes: dict, profile: SectorProfile) -> Verdict:
    axis = axes.get(rule.axis)
    metric = None if axis is None else axis.metric(rule.metric)
    applied, book, blocked = _threshold(rule, profile)

    value = None if metric is None else metric.value
    of = None if metric is None else metric.of

    if blocked:
        status, reason = NOT_APPLICABLE, f"{profile.label}: мерка не применяется"
    elif axis is not None and metric is None:
        # Ось эту величину не считает вовсе — так у кредитной организации нет
        # свободного потока в собственном смысле. Это решённое состояние, а не
        # пробел: «мы не меряем» и «мы не знаем» — разные вещи.
        status, reason = NOT_APPLICABLE, "Эта величина для такой компании не считается"
    elif applied is None and rule.mode not in ("all", "most"):
        status, reason = NOT_APPLICABLE, rule.note
    elif metric is not None and metric.suspect:
        # Число получилось, но верить ему нельзя. Пропустить такую компанию по
        # критерию хуже, чем признать, что мы не знаем: у Белуги испорченная
        # строка прибыли давала рост +42 868% и уверенное «прошла».
        status, reason = UNKNOWN, metric.suspect
    elif value is None:
        status, reason = UNKNOWN, "Нет данных"
    else:
        holds = Rule(rule.axis, rule.metric, rule.mode, applied,
                     rule.source, rule.ours, rule.note).holds(value, of)
        if holds is None:
            status, reason = UNKNOWN, "Нечем сравнить"
        elif holds:
            status, reason = PASS, None
        else:
            status, reason = FAIL, None
            rescue = _alternate(rule, axis, applied)
            if rescue is not None:
                status, reason = PASS, rescue

    return Verdict(
        axis=rule.axis,
        label=axis.label if axis else rule.axis,
        metric=rule.metric,
        metric_label=metric.label if metric else rule.metric,
        value=value,
        unit=metric.unit if metric else "",
        of=of,
        status=status,
        rule=rule,
        applied=applied,
        book=book,
        reason=reason,
        # Оговорка нужна только там, где приговор вынесен: у «нет данных» и
        # «не применяется» ослаблять нечего. Текст берётся у самой величины —
        # он зависит от того, есть ли у компании десять лет истории.
        caveat=(metric.note if rule.weak and metric is not None
                and status in (PASS, FAIL) else None),
        distorted=bool(metric is not None and metric.suspect
                       and status == UNKNOWN),
        # «Приемлемо» отличается от «хорошо» только здесь: вердикт остаётся
        # пройденным, но цвет должен совпасть с таблицей мультипликаторов.
        marginal=bool(
            status == PASS and rule.lenient and value is not None
            and (strict := _strict_edge(rule, profile)) is not None
            and not Rule(rule.axis, rule.metric, rule.mode, strict,
                         rule.source).holds(value, of)
        ),
    )


def apply(axes: list, profile: SectorProfile, standard: str = "defensive",
          ticker: str = "") -> Screen:
    """Накладывает свод критериев на готовые оси.

    Рентабельность идёт первой и вне книжных списков: у Грэма порога по ней
    нет, и она попадает в свод только потому, что на неё опирается расчёт
    роста в множителе рынка.
    """
    if standard not in RULES:
        raise ValueError(f"Неизвестный свод критериев: {standard}")

    by_key = {axis.key: axis for axis in axes}
    rules = (PROFITABILITY_RULE,) + RULES[standard]
    return Screen(
        ticker=ticker,
        standard=standard,
        profile=profile,
        verdicts=tuple(_judge(rule, by_key, profile) for rule in rules),
    )


def profile_for(db, company) -> SectorProfile:
    """Отраслевой профиль компании.

    Тип отчёта хранится на самом отчёте, а не на компании, и берётся из
    последнего годового: он сильнее строки сектора, потому что проставлен
    аналитиком вручную, а сектор приходит из внешнего справочника.
    """
    from app.models.financial_report import FinancialReport

    report = (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == company.id,
            FinancialReport.period_type == "ANNUAL",
        )
        .order_by(FinancialReport.fiscal_year.desc())
        .first()
    )
    return resolve_profile(
        getattr(company, "sector", None),
        getattr(report, "report_type", None),
        getattr(company, "sector_profile_key", None),
    )


def load(db, company, standard: str = "defensive") -> Screen:
    """То же, но сама достаёт оси и профиль компании."""
    return apply(
        screen_axes.load(db, company),
        profile_for(db, company),
        standard,
        ticker=str(company.ticker),
    )


def both(db, company) -> dict:
    """Оба свода сразу — компания редко интересна только одним из них.

    Оси считаются один раз: они от свода не зависят, и пересчитывать их ради
    второго набора порогов значит удваивать работу впустую.
    """
    axes = screen_axes.load(db, company)
    profile = profile_for(db, company)
    ticker = str(company.ticker)
    return {
        name: apply(axes, profile, name, ticker=ticker) for name in STANDARDS
    }
