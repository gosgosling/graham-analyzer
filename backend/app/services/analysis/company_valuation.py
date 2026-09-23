"""Оценка компании: от базового множителя рынка к полосе стоимости.

Второй шаг двухстороннего подхода (гл. 32, с. 601). Первый дал множитель
рынка; здесь он превращается в множитель конкретной компании и умножается на
её нормальную способность зарабатывать.

**Поправка на качество не выдумывается.** Соблазн — приписать «хорошей»
компании коэффициент 1,2 и успокоиться; но откуда 1,2, объяснить нечем. Здесь
поправки не изобретаются, потому что две из трёх уже сидят в самой формуле:

    множитель = payout / (K − g),    g = ROE × (1 − payout)

Компания с высокой отдачей капитала получает больший `g`, компания, щедрая к
владельцу, — больший числитель. Обе поправки выведены, а не назначены.

Назначенной остаётся **одна** величина: надбавка к премии за риск. Она и
несёт всё, что книга относит к качеству, но что формула сама не видит:

    ровность отдачи капитала    гл. 9, с. 144 (Winn-Dixie)
    покрытие процентов          гл. 33, с. 613–619
    глубина истории             гл. 9, с. 130

Размеры надбавок — суждение, и они собраны в одном месте ниже, чтобы с ними
можно было спорить, не читая код.

**Результат — полоса, а не число** (гл. 31, с. 482). Верхняя граница считается
по рыночной премии, нижняя — по премии с надбавкой за риск компании. Ширина
полосы сама и есть высказывание о качестве: у ровной компании с длинной
историей она узкая, у остальных широкая.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.services.analysis.market_multiple import (
    base_multiple,
    growth_is_capped,
    implied_growth,
    sustainable_growth,
)
from app.services.analysis.margin_of_safety import assess_safety
from app.services.analysis.valuation_guards import StructureVerdict

# ── Надбавки к премии за риск, процентных пунктов ──────────────────────────
# Величины назначены, а не выведены. Порядок выбран так, чтобы сумма всех
# бед — дёрганая отдача, тонкое покрытие, короткая история — давала около
# пяти пунктов, то есть удваивала рыночную премию. Компания, собравшая всё
# это разом, действительно вдвое рискованнее средней.
PENALTY_SPREAD_MODERATE = 1.0     # коридор отдачи шире образцового
PENALTY_SPREAD_WIDE = 2.0         # коридор сравним с самим уровнем
PENALTY_COVERAGE_FRAGILE = 1.5    # проценты покрыты, но без запаса
# Натянутое покрытие — надбавка вчетверо больше, и она самая крупная из всех.
# Прежде такая компания просто не показывалась; теперь показывается, и цена
# отказа должна лечь в множитель целиком, иначе смягчение вердикта превратится
# в то, чем оно быть не должно, — в поблажку.
#
# Четыре пункта выбраны так, чтобы при рыночной премии 5% требуемая доходность
# выросла примерно в полтора раза: у компании, отдающей почти всю операционную
# прибыль кредитору, владелец и должен требовать столько.
PENALTY_COVERAGE_STRAINED = 4.0

# ── Рычаг ──────────────────────────────────────────────────────────────────
# Отношение долга к собственному капиталу. Грэм в гл. 14 требует от
# промышленной компании, чтобы долг не превышал капитал, — это и есть единица.
#
# **Зачем это нужно отдельно от покрытия процентов.** Покрытие считается по
# `finance_costs`, а поле заполнено у пятнадцати компаний из сорока пяти:
# ограждение, которое у двух третей базы не может сработать, ничего не
# охраняет. Долг и капитал есть у тридцати двух, и на них опереться можно.
#
# Вторая причина глубже. Покрытие — величина из отчёта о прибылях, и она
# описывает один год. Рычаг — из баланса, и он описывает положение. У
# Аэрофлота долг вдвенадцатеро больше капитала: даже в хороший год, когда
# проценты покрыты, любое движение вниз съедает капитал акционера целиком, и
# оценка по заработку про это не знает ничего.
LEVERAGE_MODERATE = 1.0
LEVERAGE_HEAVY = 2.0
LEVERAGE_EXTREME = 4.0
PENALTY_LEVERAGE_HEAVY = 2.5
PENALTY_LEVERAGE_EXTREME = 5.0
PENALTY_HISTORY_SHORT = 1.0       # 5–6 лет
PENALTY_HISTORY_THIN = 2.0        # меньше пяти лет
PENALTY_ACCRUALS = 1.5            # половина окна держится на начислениях

# Доля искажённых лет в окне, выше которой надбавка начисляется. Один-два года
# из семи — обычное дело: у всякой компании бывает год, где движение оборотки
# перевесило заработок. Половина окна означает другое — что нормальный
# уровень выведен не из дела, а из движения денег по кругу.
ACCRUAL_PENALTY_SHARE = 0.4

# **Отказа по искажениям здесь нет, и это решение, а не упущение.** Он тут
# стоял ровно один день: порог 0,6 от окна поверх определителя, помечавшего
# 66% всех лет, вынес в отказ двадцать компаний из тридцати — Норникель,
# Новатэк, Роснефть, МТС, Белугу. Бэктест при этом показал рост точности с 54%
# до 67%, и рост был ложным: модель стала попадать чаще не потому, что считала
# лучше, а потому, что перестала считать трудное.
#
# Оценку надо давать всегда, когда есть из чего считать. Ненадёжность ряда —
# это надбавка к ставке и оговорка в тексте, а не молчание: читателю, который
# видит «сигнала нет», нечего проверять и не с чем спорить.

# Глубина, при которой история перестаёт быть поводом для надбавки. У Грэма
# десятилетие — полный набор; семь лет книга считает достаточными для оценки.
FULL_HISTORY_YEARS = 10
ENOUGH_HISTORY_YEARS = 7
SHORT_HISTORY_YEARS = 5

# Чем меряется нормальный уровень: линией тренда или простой средней.
# Пятое издание выбрало тенденцию (с. 568), и обратный тест показал, почему:
# средняя занижает растущих, промахи вверх к промахам вниз у них 24 к 1.
BASIS_TREND = "trend"
BASIS_AVERAGE = "average"

# Отдача на капитал выше этой границы почти всегда говорит о малом
# знаменателе, а не о выдающемся бизнесе: выкуп съел капитал, нематериальное
# списано, гудвил обнулён. Отличить настоящую отдачу от арифметической можно
# только парой с P/B — у Черемушек в 2021-м ROE 97% при капитале 313 млрд и
# P/B 4,3 (сырьевой сверхцикл), у Делимобиля 75% при капитале 2,6 млрд и
# P/B 17,7 (капитала просто нет).
SUSPECT_ROE = 40.0

# ── Откуда берётся рост, гл. 32 и Коттл ────────────────────────────────────
# Названия лестниц вынесены в константы: по ним расходится правило роста, и
# сверять строковый литерал в трёх местах — верный способ развести их.
LADDER_EARNINGS = "прибыль"
LADDER_CASH = "деньги"
LADDER_OWNER = "прибыль владельца"

# Выплата, выше которой удерживать уже нечего. Формула `g = ROE × (1 − payout)`
# при выплате 96% даёт полпроцента — число, которое выглядит как измеренный
# рост, хотя означает ровно обратное: источника роста нет. Округляем его до
# нуля честно, а не оставляем видимость.
#
# Порог не сто, а девяносто, потому что выплата считается за окно лет и по
# ней ходит шум: год со стопроцентной выплатой и год с восьмидесятипроцентной
# дают в среднем девяносто, и удержанного там нет всё равно.
PAYOUT_RETAINS_NOTHING = 90.0

# Потолок роста для денежной лестницы. Наблюдаемый рост потока — величина
# бойкая: у Лукойла за семь лет вышло 8,1% в год, и на бесконечном горизонте
# это загоняет зазор `K − g` в зону, где ответ определяется третьим знаком
# входа. Шесть процентов — порядок долгосрочного номинального роста
# экономики, и обгонять его вечно не может никто.
CASH_GROWTH_CAP = 6.0

# ── Поправка на активы, гл. 34 ─────────────────────────────────────────────
# Избыток: в счёт идут две трети балансовой стоимости, и к оценке по прибыли
# прибавляется треть разницы (с. 634). Недостаток: зеркально, четверть
# превышения срезается (с. 631).
ASSET_WEIGHT = 2 / 3

# Каким методом получена полоса. Читатель обязан видеть это рядом с числом:
# EPV и гл. 32 отвечают на разные вопросы, и молча подменять один другим —
# то же самое, что молча сменить единицы измерения.
METHOD_COTTLE = "cottle"
METHOD_EPV = "epv"
METHOD_LABELS = {
    METHOD_COTTLE: "множитель главы 32",
    METHOD_EPV: "способность зарабатывать (EPV)",
}
EXCESS_SHARE = 1 / 3
SHORTFALL_MULTIPLE = 2.0
SHORTFALL_SHARE = 1 / 4


@dataclass
class RiskPenalty:
    """Надбавка к рыночной премии за то, чего формула сама не видит."""

    spread: float = 0.0
    coverage: float = 0.0
    leverage: float = 0.0
    history: float = 0.0
    accruals: float = 0.0
    notes: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(self.spread + self.coverage + self.leverage
                     + self.history + self.accruals, 2)

    def as_dict(self) -> dict:
        return {
            "spread": self.spread,
            "coverage": self.coverage,
            "history": self.history,
            "leverage": self.leverage,
            "accruals": self.accruals,
            "total": self.total,
            "notes": self.notes,
        }


def debt_to_equity(
    debt: Optional[float],
    equity: Optional[float],
) -> Optional[float]:
    """Рычаг: во сколько раз долг больше собственного капитала.

    Отрицательный или нулевой капитал величины не даёт — там отношение не
    определено, а положение описывается словами, а не числом.
    """
    if debt is None or equity is None:
        return None
    if float(equity) <= 0:
        return None
    return round(float(debt) / float(equity), 2)


def risk_penalty(
    stability_label: Optional[str],
    coverage_verdict: Optional[str],
    history_years: Optional[int],
    distortion: Optional[dict] = None,
    leverage: Optional[float] = None,
) -> RiskPenalty:
    """Собирает надбавку из четырёх измеримых признаков.

    Неизвестное не штрафуется. Отсутствие данных — не то же самое, что
    плохие данные, и накидывать пункты за незаполненное поле значило бы
    наказывать компанию за нашу же неполноту.
    """
    penalty = RiskPenalty()

    if stability_label == "умеренно":
        penalty.spread = PENALTY_SPREAD_MODERATE
        penalty.notes.append("отдача на капитал колеблется шире образцовой")
    elif stability_label == "разбросано":
        penalty.spread = PENALTY_SPREAD_WIDE
        penalty.notes.append("коридор отдачи на капитал сравним с самим уровнем")

    if coverage_verdict == "strained":
        penalty.coverage = PENALTY_COVERAGE_STRAINED
        penalty.notes.append(
            "долг обслуживается почти всей операционной прибылью"
        )
    elif coverage_verdict == "fragile":
        penalty.coverage = PENALTY_COVERAGE_FRAGILE
        penalty.notes.append("проценты покрыты без запаса")

    if history_years is not None:
        if history_years < SHORT_HISTORY_YEARS:
            penalty.history = PENALTY_HISTORY_THIN
            penalty.notes.append(f"история всего {history_years} лет")
        elif history_years < ENOUGH_HISTORY_YEARS:
            penalty.history = PENALTY_HISTORY_SHORT
            penalty.notes.append(f"история {history_years} лет — меньше семи")

    # Искажённые начислениями годы из ряда не выбрасываются — см.
    # `distortion_summary`. Но если их набралось много, нормальный уровень
    # выведен из движения оборотного капитала, а не из заработка, и цена за
    # такую оценку должна быть ниже.
    share = (distortion or {}).get("share")
    if share is not None and share > ACCRUAL_PENALTY_SHARE:
        penalty.accruals = PENALTY_ACCRUALS
        years = ", ".join(str(y) for y in distortion.get("years", []))
        penalty.notes.append(
            f"{distortion['count']} года из {distortion['of']} держатся на "
            f"начислениях, а не на заработке ({years})"
        )

    # Рычаг — из баланса, и он описывает положение, а не один год. У
    # Аэрофлота долг вдвенадцатеро больше капитала: даже когда проценты
    # покрыты, любое движение вниз съедает капитал акционера целиком, и оценка
    # по заработку про это не знает ничего.
    if leverage is not None:
        if leverage > LEVERAGE_EXTREME:
            penalty.leverage = PENALTY_LEVERAGE_EXTREME
            penalty.notes.append(
                f"долг больше капитала в {leverage:.0f} раз — капитал "
                f"акционера съедается любым движением вниз"
            )
        elif leverage > LEVERAGE_HEAVY:
            penalty.leverage = PENALTY_LEVERAGE_HEAVY
            penalty.notes.append(
                f"долг больше капитала в {leverage:.1f} раза — при пороге "
                f"главы 14 в один к одному"
            )

    return penalty


# ── Запасной метод: EPV ────────────────────────────────────────────────────
# Выплата, ниже которой формула гл. 32 перестаёт работать. Множитель там равен
# `payout / (K − g)`, и при нулевом числителе он обращается в ноль: компания,
# не платящая владельцу, получает оценку «ноль рублей». Это неверно — она
# по-прежнему зарабатывает, просто деньги пока остаются внутри.
EPV_PAYOUT_FLOOR = 5.0


def earning_power_value(
    normal_earnings_per_share: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    extra_premium: float = 0.0,
) -> Optional[float]:
    """Стоимость способности зарабатывать: прибыль ÷ требуемая доходность.

    Гринвальд, earning power value. Формула предельно скупа и именно этим
    полезна: она оценивает то, что дело зарабатывает **сегодня**, и не
    содержит ни роста, ни выплаты. Ни одного допущения о будущем в ней нет —
    поэтому там, где спорить не о чем, спорить и не приходится.

    Родство с гл. 32 прямое, а не по аналогии. При выплате 100% и нулевом
    росте формула Коттла `P = D / (K − g)` превращается в `P = E / K`, то есть
    в EPV буквально. Расходятся методы ровно настолько, насколько компания
    удерживает прибыль, и потому EPV — не «другая школа», а тот же расчёт в
    предельном случае.

    **Что EPV не видит.** Он не видит роста вовсе — ни хорошего, ни плохого.
    Для компании, которая удерживает прибыль и зарабатывает на неё выше
    стоимости капитала, он даёт систематически заниженную оценку, и брать его
    там, где работает гл. 32, нельзя: он годится как нижняя граница, но не как
    ответ.
    """
    if normal_earnings_per_share is None or normal_earnings_per_share <= 0:
        return None
    if risk_free_rate is None or risk_premium is None:
        return None
    required = float(risk_free_rate) + float(risk_premium) + float(extra_premium)
    if required <= 0:
        return None
    return round(float(normal_earnings_per_share) / (required / 100.0), 2)


# ── Чистая стоимость оборотных активов, гл. 15 ─────────────────────────────
# Доля NCAV, выше которой Грэм покупать отказывался. «Разумный инвестор»,
# гл. 15: цена не выше двух третей чистой стоимости оборотных активов. Треть —
# запас на то, что при ликвидации активы выручат меньше балансовой величины.
NCAV_THRESHOLD = 2 / 3


def net_current_asset_value(
    current_assets: Optional[float],
    total_liabilities: Optional[float],
    shares: Optional[float],
) -> Optional[float]:
    """NCAV на акцию: оборотные активы минус ВСЕ обязательства.

    Гл. 15. Приём намеренно жесток: внеоборотные активы — здания, скважины,
    лицензии — не учитываются вовсе, а обязательства вычитаются целиком,
    включая долгосрочные. Получается оценка того, что осталось бы владельцу,
    если бы дело закрыли завтра и продали только легко продаваемое.

    Смысл в том, что эта величина **не зависит от прибыли**. Она отвечает
    там, где молчат и гл. 32, и EPV: у компании с убытком способности
    зарабатывать нет, а баланс есть.

    **Чего ждать от неё на практике.** Грэм писал это в 1949 году, разбирая
    рынок после депрессии, и сам называл такие бумаги редкостью. На нашей
    базе NCAV положителен у двух компаний из сорока пяти, и обе стоят дороже
    него. Это не сбой расчёта и не повод смягчать порог — это ответ: чистых
    «сигарных окурков» на текущем рынке нет.
    """
    if None in (current_assets, total_liabilities, shares):
        return None
    if not shares or float(shares) <= 0:
        return None
    value = float(current_assets) - float(total_liabilities)
    # Величины в отчёте — миллионы; цена акции — рубли.
    return round(value * 1_000_000 / float(shares), 2)


def ncav_check(
    ncav_per_share: Optional[float],
    price: Optional[float],
) -> Optional[dict]:
    """Проходит ли цена тест гл. 15. Отдельный ответ, а не часть полосы.

    Соединять его с оценкой по заработку нельзя: это два разных вопроса —
    «сколько дело зарабатывает» и «сколько осталось бы при закрытии», — и
    усреднять их значило бы получить величину, не отвечающую ни на один.
    """
    if ncav_per_share is None:
        return None
    edge = round(ncav_per_share * NCAV_THRESHOLD, 2)
    passes = (
        price is not None and price > 0
        and ncav_per_share > 0 and float(price) <= edge
    )

    # Разряды отделяются здесь, а не через `replace` по всей строке: замена по
    # строке съедала и грамматические запятые вместе с разрядными.
    def rub(value):
        return f"{value:,.0f}".replace(",", "\u00a0")

    if ncav_per_share <= 0:
        note = (
            f"NCAV отрицателен ({rub(ncav_per_share)} ₽ на акцию): "
            f"обязательства больше оборотных активов, и при закрытии владельцу "
            f"не осталось бы ничего"
        )
    elif passes:
        note = (
            f"цена {rub(price)} ₽ ниже двух третей NCAV ({rub(edge)} ₽) — "
            f"случай гл. 15: дело отдают дешевле его оборотных активов"
        )
    else:
        note = (
            f"NCAV {rub(ncav_per_share)} ₽ на акцию, порог гл. 15 — "
            f"{rub(edge)} ₽" + (f"; цена {rub(price)} ₽ выше" if price else "")
        )
    return {
        "per_share": ncav_per_share,
        "threshold": edge,
        "passes": passes,
        "note": note,
    }


def company_multiple(
    payout: Optional[float],
    roe: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    extra_premium: float = 0.0,
    growth_cap: Optional[float] = None,
):
    """Множитель компании по её собственным выплате и отдаче капитала.

    Та же формула, что и для рынка, но с числами компании. Никакого
    отдельного «коэффициента качества» здесь нет и быть не должно: высокая
    отдача уже даёт больший рост, щедрая выплата — больший числитель.
    """
    if risk_premium is None:
        return None
    growth = sustainable_growth(roe, payout, growth_cap)
    return base_multiple(payout, risk_free_rate, risk_premium + extra_premium, growth)


def ladder_growth(
    ladder: str,
    roe: Optional[float],
    payout: Optional[float],
    observed: Optional[float] = None,
    growth_cap: Optional[float] = None,
) -> tuple:
    """Какой рост подставлять в множитель этой лестницы. → (g, откуда, оговорка).

    Одного `g` на все три лестницы не бывает, и это не тонкость настройки, а
    разная механика.

    **Прибыль и прибыль владельца.** Рост финансируется удержанием: то, что
    не роздано, прибавляется к капиталу, капитал зарабатывает свою отдачу,
    прибыль следующего года выше. Отсюда `g = ROE × (1 − payout)` — правило
    Коттла, и его смысл в том, что рост нельзя предположить, его нужно
    профинансировать.

    Но у формулы есть край. При выплате около ста процентов удержанного нет,
    и она честно выдаёт около нуля — а выглядит это как измеренный рост в
    полпроцента. Выше `PAYOUT_RETAINS_NOTHING` ставим ноль прямо и говорим,
    почему: так читателю видно, что источника роста нет, а не что он мал.

    **Деньги.** Здесь выводить рост из удержания нельзя вовсе, и это главная
    поправка. Свободный поток растёт от капекса, а капекс из свободного
    потока уже вычтен: подставить туда удержание значит посчитать один и тот
    же источник дважды. Поэтому рост берётся наблюдаемый — наклон самого ряда
    потока, — и обязательно с потолком.

    Отрицательный наблюдаемый рост не переносится в формулу. Сжимающийся
    поток — повод не покупать, а не повод получить множитель ниже: вечное
    сжатие формула Гордона описывает не лучше, чем вечный взлёт, и честнее
    оценить компанию по нулевому росту, а сжатие показать отдельно.
    """
    if ladder == LADDER_CASH:
        cap = CASH_GROWTH_CAP if growth_cap is None else min(float(growth_cap),
                                                             CASH_GROWTH_CAP)
        if observed is None:
            return 0.0, "нет ряда", (
                "рост потока измерить не по чему — взят ноль"
            )
        value = float(observed)
        if value <= 0:
            return 0.0, "поток не растёт", (
                f"наблюдаемый рост потока {value:.1f}% — в формулу взят ноль: "
                f"вечное сжатие она не описывает"
            )
        if value > cap:
            return cap, "наблюдаемый, подрезан", (
                f"наблюдаемый рост потока {value:.1f}% подрезан до {cap:.1f}% — "
                f"обгонять экономику вечно нельзя"
            )
        return round(value, 2), "наблюдаемый", None

    if payout is not None and float(payout) >= PAYOUT_RETAINS_NOTHING:
        return 0.0, "выплата", (
            f"выплата {float(payout):.0f}% — удерживать нечего, рост взят "
            f"нулевым, а не выведен из остатка"
        )

    return sustainable_growth(roe, payout, growth_cap), "удержание", None


def asset_adjustment(
    value: Optional[float],
    book_value_per_share: Optional[float],
) -> tuple:
    """Поправка на избыток или нехватку активов. Возвращает (оценка, пояснение).

    Пример из книги (с. 634): способность зарабатывать 33 на акцию,
    балансовая стоимость 100, оценка по прибыли и дивидендам 30. Тогда
    ⅔ × 100 = 67; 67 − 30 = 37; итог 30 + ⅓ × 37 = 42.

    Зеркальная поправка (с. 631) срезает четверть превышения над двойной
    балансовой стоимостью. Книга формулирует её как «сократить на четверть»;
    читаем это как четверть **превышения**, а не всей оценки, — иначе на
    границе возникал бы обрыв, которого в тексте нет.
    """
    if value is None or book_value_per_share is None or book_value_per_share <= 0:
        return value, None

    counted_assets = ASSET_WEIGHT * book_value_per_share
    if counted_assets > value:
        excess = counted_assets - value
        adjusted = value + EXCESS_SHARE * excess
        return round(adjusted, 2), (
            f"активы избыточны: ⅔ балансовой стоимости {counted_assets:.0f} выше "
            f"оценки по прибыли {value:.0f}, к оценке добавлена треть разницы"
        )

    ceiling = SHORTFALL_MULTIPLE * book_value_per_share
    if value > ceiling:
        adjusted = value - SHORTFALL_SHARE * (value - ceiling)
        return round(adjusted, 2), (
            f"активов не хватает: оценка {value:.0f} выше двойной балансовой "
            f"стоимости {ceiling:.0f}, превышение срезано на четверть"
        )

    return round(value, 2), None


@dataclass
class Ladder:
    """Оценка по одной из трёх лестниц: прибыль, деньги, прибыль владельца."""

    name: str
    normal_per_share: float
    multiple: float
    value: float
    adjusted: Optional[float] = None
    asset_note: Optional[str] = None
    # Рост своей лестницы и то, откуда он взят. Хранится здесь, а не в полосе,
    # потому что у денежной лестницы он другой по существу — см. ladder_growth.
    growth: Optional[float] = None
    growth_source: Optional[str] = None
    growth_note: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "normal_per_share": round(self.normal_per_share, 2),
            "multiple": self.multiple,
            "value": round(self.value, 2),
            "adjusted": self.adjusted,
            "asset_note": self.asset_note,
            "growth": self.growth,
            "growth_source": self.growth_source,
            "growth_note": self.growth_note,
        }


@dataclass
class ValueBand:
    """Полоса стоимости и всё, что нужно, чтобы ей не поверить зря."""

    low: Optional[float] = None
    high: Optional[float] = None
    # Та же полоса до поправки на активы. Нужна отдельно, потому что поправка
    # стягивает обе границы к ⅔ балансовой стоимости и тем самым скрывает
    # надбавку за риск: у Газпрома полоса после поправки схлопывается с
    # 71–120 до 219–225, и по её ширине уже ничего не прочитать.
    low_by_earnings: Optional[float] = None
    high_by_earnings: Optional[float] = None
    # Опорная оценка для сигнала: лестница прибыли при множителе с надбавкой
    # за риск. Границы полосы для этого не годятся — низ полосы берётся как
    # минимум по всем трём лестницам, то есть это худшая ступень при худшем
    # множителе, и запас от неё не считается осмысленно: у Лукойла низ даёт
    # прибыль владельца в 2 123 ₽ при цене 5 234, и «запас −146%» не сообщает
    # ничего, кроме того, что две лестницы разошлись.
    #
    # Опора берётся именно по прибыли: это та величина, которую оценивает
    # формула гл. 32, и та, с которой сопоставима доходность облигации.
    conservative: Optional[float] = None
    ladders: list = field(default_factory=list)
    penalty: Optional[RiskPenalty] = None
    basis: str = BASIS_TREND
    method: str = METHOD_COTTLE
    multiple_high: Optional[float] = None
    multiple_low: Optional[float] = None
    growth: Optional[float] = None
    growth_source: Optional[str] = None
    growth_uncapped: Optional[float] = None
    growth_capped: bool = False
    refused: bool = False
    reason: Optional[str] = None
    warnings: list = field(default_factory=list)

    @property
    def width(self) -> Optional[float]:
        """Во сколько раз верхняя граница выше нижней — до поправки на активы.

        Именно до: ширина полосы говорит о качестве компании, а поправка на
        активы про качество ничего не знает и только сдвигает обе границы.
        """
        low, high = self.low_by_earnings, self.high_by_earnings
        if not low or not high or low <= 0:
            return None
        return round(high / low, 2)

    @property
    def asset_lift(self) -> Optional[float]:
        """Во сколько раз поправка на активы сдвинула оценку."""
        if not self.high or not self.high_by_earnings or self.high_by_earnings <= 0:
            return None
        return round(self.high / self.high_by_earnings, 2)

    def as_dict(self) -> dict:
        return {
            "low": self.low,
            "high": self.high,
            "low_by_earnings": self.low_by_earnings,
            "high_by_earnings": self.high_by_earnings,
            "conservative": self.conservative,
            "width": self.width,
            "asset_lift": self.asset_lift,
            "ladders": [item.as_dict() for item in self.ladders],
            "penalty": self.penalty.as_dict() if self.penalty else None,
            "basis": self.basis,
            "method": self.method,
            "method_label": METHOD_LABELS[self.method],
            "multiple_high": self.multiple_high,
            "multiple_low": self.multiple_low,
            "growth": self.growth,
            "growth_source": self.growth_source,
            "growth_uncapped": self.growth_uncapped,
            "growth_capped": self.growth_capped,
            "refused": self.refused,
            "reason": self.reason,
            "warnings": self.warnings,
        }


def value_band(
    payout: Optional[float],
    roe: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    normal_earnings: dict,
    book_value_per_share: Optional[float] = None,
    structure: Optional[StructureVerdict] = None,
    stability_label: Optional[str] = None,
    history_years: Optional[int] = None,
    cash_backing: Optional[float] = None,
    growth_cap: Optional[float] = None,
    basis: str = "trend",
    observed_growth: Optional[dict] = None,
    distortion: Optional[dict] = None,
    leverage: Optional[float] = None,
) -> ValueBand:
    """Полоса стоимости на акцию.

    `normal_earnings` — словарь «название лестницы → нормальная величина на
    акцию», например {'прибыль': 916.0, 'деньги': 1115.0}. Что именно туда
    положено — среднюю или тренд — решает вызывающий; `basis` только
    записывается в результат, чтобы читатель знал, что перед ним. Каждая лестница
    оценивается отдельно: расхождение между ними и есть сообщение о том,
    насколько бухгалтерия расходится с кассой.

    Ограждения (гл. 33 и 34) стоят до расчёта. Компанию, у которой проценты
    съедают прибыль, оценивать формулой нельзя — не потому, что она плохая, а
    потому, что число будет ложным.
    """
    band = ValueBand(basis=basis)

    if structure is not None and not structure.valuation_allowed:
        band.refused = True
        band.reason = structure.reason
        return band

    band.penalty = risk_penalty(
        stability_label,
        structure.verdict if structure else None,
        history_years,
        distortion,
        leverage,
    )

    # Рост базовой лестницы — прибыли. Он же показывается как «рост компании»:
    # денежный считается отдельно и живёт внутри своей ступени.
    band.growth, band.growth_source, growth_note = ladder_growth(
        LADDER_EARNINGS, roe, payout, growth_cap=growth_cap
    )
    band.growth_uncapped = sustainable_growth(roe, payout)
    band.growth_capped = growth_is_capped(roe, payout, growth_cap)
    if growth_note:
        band.warnings.append(growth_note)

    base = base_multiple(payout, risk_free_rate, risk_premium, band.growth)

    # Запасной путь. Формула гл. 32 требует выплаты и роста; там, где их нет,
    # она даёт либо ноль, либо ничего — и компания, которая исправно
    # зарабатывает, выпадает из оценки целиком. Так выпадало семнадцать
    # компаний из сорока пяти: не платящие владельцу и слишком молодые для
    # того, чтобы посчитать ровность отдачи.
    #
    # EPV на их месте отвечает тем, что знает: прибыль ÷ требуемая доходность.
    # Это заведомо нижняя граница — роста в ней нет вовсе, — и потому метод
    # назван в выдаче явно. Читатель должен видеть не только число, но и то,
    # какой формулой оно получено.
    if base is None or base.value is None:
        return _epv_band(
            band, normal_earnings, risk_free_rate, risk_premium,
            book_value_per_share, basis,
            reason=(base.problem if base else "не хватает данных"),
            payout=payout,
        )

    band.multiple_high = base.value
    low_base = base_multiple(
        payout, risk_free_rate,
        None if risk_premium is None else risk_premium + band.penalty.total,
        band.growth,
    )
    band.multiple_low = low_base.value if low_base else None

    if band.growth_capped:
        band.warnings.append(
            f"выведенный рост {band.growth_uncapped}% подрезан до {band.growth}% — "
            f"такая отдача на капитал держится на малом знаменателе, а расти "
            f"быстрее экономики вечно нельзя"
        )
    if cash_backing is not None and cash_backing < 0.6:
        band.warnings.append(
            f"прибыль обеспечена деньгами лишь на {cash_backing:.0%} — "
            f"оценке по прибыли верить нельзя"
        )
    if history_years is not None and history_years < FULL_HISTORY_YEARS:
        band.warnings.append(
            f"история {history_years} лет вместо десяти — нормальная прибыль "
            f"посчитана на коротком ряду"
        )

    observed_growth = observed_growth or {}
    values, raw_values = [], []
    for name, normal in normal_earnings.items():
        if normal is None or normal <= 0:
            continue

        growth, source, note = ladder_growth(
            name, roe, payout, observed_growth.get(name), growth_cap
        )
        top = base_multiple(payout, risk_free_rate, risk_premium, growth)
        if top is None or top.value is None:
            # Ступень, для которой множителя не существует, молча пропускается:
            # она не должна ни сужать полосу, ни отменять остальные.
            continue
        bottom = base_multiple(
            payout, risk_free_rate,
            None if risk_premium is None else risk_premium + band.penalty.total,
            growth,
        )

        raw = top.value * float(normal)
        adjusted, asset_note = asset_adjustment(raw, book_value_per_share)
        if name == LADDER_EARNINGS and bottom is not None and bottom.value:
            band.conservative = round(bottom.value * float(normal), 2)
        band.ladders.append(Ladder(
            name=name,
            normal_per_share=float(normal),
            multiple=top.value,
            value=raw,
            adjusted=adjusted,
            asset_note=asset_note,
            growth=growth,
            growth_source=source,
            growth_note=note,
        ))
        values.append(adjusted if adjusted is not None else raw)
        raw_values.append(raw)

        if bottom is not None and bottom.value:
            low_raw = bottom.value * float(normal)
            low_adjusted, _ = asset_adjustment(low_raw, book_value_per_share)
            values.append(low_adjusted if low_adjusted is not None else low_raw)
            raw_values.append(low_raw)

    if not values:
        band.refused = True
        band.reason = "нормальная прибыль не положительна ни по одной лестнице"
        return band

    band.low = round(min(values), 2)
    band.high = round(max(values), 2)
    band.low_by_earnings = round(min(raw_values), 2)
    band.high_by_earnings = round(max(raw_values), 2)
    return band


def denominator_note(
    roe: Optional[float],
    price_to_book: Optional[float],
) -> Optional[dict]:
    """Не держится ли высокая отдача на малом капитале.

    Возвращает не приговор, а пару чисел рядом: без P/B высокий ROE читается
    как «выдающийся бизнес», хотя чаще означает «капитала почти нет».
    """
    if roe is None or roe <= SUSPECT_ROE:
        return None
    return {
        "roe": round(float(roe), 2),
        "price_to_book": None if price_to_book is None else round(float(price_to_book), 2),
        "reason": (
            f"отдача на капитал {roe:.0f}% — величина, которую надо читать "
            f"вместе с P/B: столько зарабатывают не на выдающемся бизнесе, а "
            f"на маленьком балансовом капитале"
        ),
    }


def priced_in_growth(
    price: Optional[float],
    normal_per_share: Optional[float],
    payout: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    affordable_growth: Optional[float],
) -> Optional[dict]:
    """Какой рост заложен в текущую цену — и по силам ли он компании.

    Оценка, которая говорит «дороже полосы», сама по себе бесполезна: она
    объявляет рынок неправым, не объясняя, в чём именно расхождение. Обратный
    ход формулы превращает приговор в вопрос. Позитив при цене 947 ₽ и
    нормальной прибыли около 28 ₽ оценивается рынком так, будто дивиденды
    растут на столько-то в год; компания при своей отдаче и выплате способна
    на столько-то. Разрыв между двумя числами — предмет спора, а «дорого» —
    нет.

    Возвращается None, когда переворачивать нечего: без выплаты формула
    необратима, при убыточной нормальной прибыли множителя не существует.
    """
    if not price or not normal_per_share or normal_per_share <= 0:
        return None
    if not payout or payout <= 0:
        return None

    multiple = round(price / normal_per_share, 2)
    priced = implied_growth(payout, risk_free_rate, risk_premium, multiple)
    if priced is None:
        return None

    gap = None
    if affordable_growth is not None:
        gap = round(priced - affordable_growth, 2)

    return {
        "multiple_paid": multiple,
        "growth_priced_in": priced,
        "growth_affordable": affordable_growth,
        # Насколько рынок оптимистичнее того, что компания вытягивает сама.
        "gap": gap,
        "demanding": gap is not None and gap > 0,
    }


# ── Сборка оценки по данным компании ───────────────────────────────────────

# Окно нормализации по умолчанию. Семь лет — то, что «Разумный инвестор»
# считает достаточным для оценки уровня прибыли (гл. 11).
DEFAULT_WINDOW = 7


def assess(
    db,
    company,
    assumption,
    window: int = DEFAULT_WINDOW,
    basis: str = BASIS_TREND,
    screen_clears: Optional[bool] = None,
) -> dict:
    """Полная оценка компании: полоса стоимости и всё, из чего она сложилась.

    Собирает вместе четыре куска, посчитанных отдельно: нормальную способность
    зарабатывать (три лестницы), ровность отдачи капитала, приговор структуре
    капитала и допущения об уровне рынка. Возвращает словарь, потому что
    страница показывает не только ответ, но и путь к нему.
    """
    from app.models.financial_report import FinancialReport
    from app.models.multiplier import Multiplier
    from app.services.analysis.earning_power import (
        analyze, buyback_payout, distortion_summary, load_points,
        payout_over_window, retention_test, stability,
    )
    from app.services.analysis.valuation_guards import molodovsky, structure

    points = load_points(db, company.id)
    if not points:
        return {"available": False, "reason": "нет годовых отчётов"}

    is_lender = str(getattr(company, "company_type", "")).upper().endswith("LENDER")
    power = analyze(points, with_cash=not is_lender)
    steadiness = stability(points)
    # Возврат владельцу — не только дивиденды. Выкуп доносит те же деньги,
    # просто не всем сразу, и без него формула объявляет скрягой каждого, кто
    # предпочитает выкуп выплате. У Коттла этого нет: пятое издание вышло
    # раньше, чем выкупы стали массовыми.
    dividend_payout = payout_over_window(points, window)
    buyback = buyback_payout(points, window)
    payout = dividend_payout
    if dividend_payout is not None and buyback is not None:
        payout = round(dividend_payout + buyback, 2)

    latest = (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == company.id,
            FinancialReport.period_type == "ANNUAL",
        )
        .order_by(FinancialReport.fiscal_year.desc())
        .first()
    )
    # Ключевая ставка нужна для проверки самих финансовых расходов: величина
    # заносится по-разному — где нетто, где без лизинговых процентов, — и
    # верить ей в одиночку нельзя. См. `valuation_guards.costs_are_credible`.
    key_rate = None
    if latest is not None:
        from app.models.key_rate import KeyRate

        row = (
            db.query(KeyRate.avg_rate)
            .filter(KeyRate.year == latest.fiscal_year)
            .first()
        )
        key_rate = None if row is None else float(row[0])

    def _num(field):
        value = getattr(latest, field, None) if latest else None
        return None if value is None else float(value)

    verdict = structure(
        _num("operating_profit"),
        _num("finance_costs"),
        lease_interest=_num("lease_interest"),
        debt=_num("debt"),
        key_rate=key_rate,
    )

    # Рычаг и тест гл. 15 у финансовых институтов не считаются вовсе.
    #
    # У банка отношение долга к капиталу смысла не имеет: заёмные средства там
    # сырьё, а не бремя. Тест гл. 15 тем более: «оборотные активы» кредитора —
    # это выданные кредиты, и вычитать из них все обязательства, то есть
    # вклады, значит считать не запас, а разницу двух сторон одного баланса.
    #
    # Биржа сюда же. Раньше она выпадала случайно — по незаполненному полю
    # оборотных активов, — и заполни его кто-нибудь, MOEX получила бы тест,
    # который к ней неприменим. Правило должно быть названо, а не получаться
    # само.
    financial = str(getattr(latest, "report_type", "")).lower().endswith(
        ("bank", "exchange")
    ) if latest is not None else False

    leverage = None if financial else debt_to_equity(_num("debt"), _num("equity"))

    # Лестницы: у банка свободный поток не измеряет заработок, поэтому их одна.
    ladders, averages, observed = {}, {}, {}
    for name, estimate in (
        (LADDER_EARNINGS, power.earnings.get(window)),
        (LADDER_CASH, power.cash.get(window)),
        (LADDER_OWNER, power.owner.get(window)),
    ):
        if estimate is None or estimate.per_share is None:
            continue
        averages[name] = estimate.per_share.value
        # Наблюдаемый рост — наклон самой лестницы. Нужен денежной ступени, где
        # выводить рост из удержания нельзя: поток растёт от капекса, а капекс
        # из потока уже вычтен.
        if estimate.trend is not None:
            observed[name] = estimate.trend.annual_growth
        # Тренд там, где он определён; иначе средняя. На коротком ряду линию
        # проводить не по чему, и подменять её нечем.
        if basis == BASIS_TREND and estimate.trend is not None:
            ladders[name] = estimate.trend.value
        else:
            ladders[name] = estimate.per_share.value

    backing = power.backing.get(window, {}).get("ratio")
    distortion = distortion_summary(points, window)
    band = value_band(
        payout=payout,
        roe=steadiness.median if steadiness else None,
        risk_free_rate=float(assumption.risk_free_rate),
        risk_premium=float(assumption.risk_premium),
        normal_earnings=ladders,
        book_value_per_share=power.book_value_per_share,
        structure=verdict,
        stability_label=steadiness.label if steadiness else None,
        history_years=len(points),
        cash_backing=backing,
        basis=basis,
        observed_growth=observed,
        distortion=distortion,
        leverage=leverage,
        growth_cap=(
            float(assumption.long_run_growth)
            if getattr(assumption, "long_run_growth", None) is not None else None
        ),
    )

    price = float(company.current_price) if company.current_price is not None else None
    latest_point = max(points, key=lambda p: p.year)
    artifact = molodovsky(price, latest_point.eps, ladders.get("прибыль"))
    latest_multiple = (
        db.query(Multiplier)
        .filter(Multiplier.company_id == company.id, Multiplier.type == "current")
        .order_by(Multiplier.date.desc())
        .first()
    )
    denominator = denominator_note(
        steadiness.median if steadiness else None,
        latest_multiple.pb_ratio if latest_multiple else None,
    )
    # Запас прочности. Свод критериев — рубильник, а не слагаемое: дешёвая
    # плохая компания у Грэма не выгодна, она плохая. Непрохождение свода не
    # обязано ломать оценку, поэтому промах здесь гасится — сигнал просто
    # останется без рубильника.
    # Свод считается здесь только если вызывающий его не принёс. Сводная
    # таблица рынка считает его сама на каждую строку, и пересчитывать вторым
    # заходом значило бы удваивать самую дорогую часть запроса.
    clears = screen_clears
    if clears is None:
        try:
            from app.services.analysis import screen

            clears = screen.load(db, company, "defensive").clears
        except Exception:
            clears = None

    # Тест гл. 15 считается для всех, а не только для отказанных. Это
    # самостоятельный критерий Грэма, и у прибыльной компании он тоже
    # осмыслен: «дорого по заработку, но ниже оборотных активов» — редкое и
    # содержательное сочетание, которое нельзя увидеть, если считать NCAV
    # только там, где всё остальное уже провалилось.
    ncav = None
    if not financial:
        ncav = ncav_check(
            net_current_asset_value(
                _num("current_assets"), _num("total_liabilities"),
                _num("shares_issued"),
            ),
            price,
        )

    safety = assess_safety(
        price=price,
        reference=band.conservative or band.low,
        band_high=band.high,
        normal_earnings_per_share=ladders.get(LADDER_EARNINGS),
        risk_free_rate=float(assumption.risk_free_rate),
        screen_clears=clears,
        book_value_per_share=power.book_value_per_share,
        # Признаки ловушки стоимости: дисконт к балансу и утечка удержанного.
        price_to_book=(
            float(latest_multiple.pb_ratio)
            if latest_multiple and latest_multiple.pb_ratio is not None else None
        ),
        retention=retention_test(points, window),
        ncav=ncav,
        leverage=leverage,
        coverage_verdict=verdict.verdict if verdict else None,
        structure_coverage=verdict.coverage if verdict else None,
    )

    priced_in = priced_in_growth(
        price,
        ladders.get("прибыль"),
        payout,
        float(assumption.risk_free_rate),
        float(assumption.risk_premium),
        band.growth,
    )

    return {
        "available": True,
        "window": window,
        "price": price,
        "payout": payout,
        "payout_dividends": dividend_payout,
        "payout_buyback": buyback,
        "history_years": len(points),
        "book_value_per_share": (
            round(power.book_value_per_share, 2)
            if power.book_value_per_share else None
        ),
        "stability": steadiness.as_dict() if steadiness else None,
        "structure": verdict.as_dict(),
        "cash_backing": backing,
        "band": band.as_dict(),
        "ncav": ncav,
        # Сигнал по цене: полоса сама по себе ответа не даёт, её надо
        # соотнести со ставкой и со сводом критериев.
        "safety": safety.as_dict(),
        "distortion": distortion,
        # Средняя остаётся рядом: расхождение с трендом показывает, насколько
        # сильно ряд движется, и его надо видеть, а не прятать за выбором.
        "averages": {name: round(value, 2) for name, value in averages.items()},
        "trends": {
            name: estimate.trend.as_dict()
            for name, estimate in (
                ("прибыль", power.earnings.get(window)),
                ("деньги", power.cash.get(window)),
                ("прибыль владельца", power.owner.get(window)),
            )
            if estimate is not None and estimate.trend is not None
        },
        "molodovsky": artifact.as_dict(),
        "priced_in": priced_in,
        "denominator": denominator,
        "direction": (
            power.eps_direction[window].as_dict()
            if window in power.eps_direction else None
        ),
        "assumption": {
            "year": assumption.year,
            "risk_free_rate": float(assumption.risk_free_rate),
            "risk_premium": float(assumption.risk_premium),
        },
        # Отношение цены к границам полосы: больше единицы — рынок платит выше
        # оценки. Считается здесь, чтобы страница не делила сама.
        "price_to_low": (
            round(price / band.low, 2) if price and band.low else None
        ),
        "price_to_high": (
            round(price / band.high, 2) if price and band.high else None
        ),
    }


def series(db, company, window: int = DEFAULT_WINDOW) -> dict:
    """Ряды по годам плюс средние за окно — то, из чего сложилась оценка.

    Цена берётся из кэша мультипликаторов, а не из дневной истории цен: там
    она лежит на дату отчёта и в том масштабе, в каком акция тогда торговалась.
    Дневной ряд хранится всего за несколько месяцев и рядом с десятилетними
    фундаментальными величинами всё равно не встал бы.

    Средние отдаются отдельно от ряда: линия средней рисуется по всему полю,
    а не по годам, и смешивать её с точками ряда нельзя.
    """
    from app.services.analysis.earning_power import analyze, load_points

    points = load_points(db, company.id)
    if not points:
        return {"available": False, "years": [], "averages": {}}

    is_lender = str(getattr(company, "company_type", "")).upper().endswith("LENDER")
    power = analyze(points, with_cash=not is_lender)

    def rounded(value):
        return None if value is None else round(float(value), 2)

    years = [
        {
            "year": point.year,
            "eps": rounded(point.eps),
            "fcf_per_share": rounded(point.fcf_per_share),
            "owner_earnings_per_share": rounded(point.owner_earnings_per_share),
            "book_value_per_share": rounded(point.book_value_per_share),
            "dividends_per_share": rounded(point.dividends_per_share),
            "roe": rounded(point.roe),
            "price": rounded(_price_at(db, company.id, point.year)),
        }
        for point in sorted(points, key=lambda p: p.year)
    ]

    averages = {}
    for key, estimate in (
        ("eps", power.earnings.get(window)),
        ("fcf_per_share", power.cash.get(window)),
        ("owner_earnings_per_share", power.owner.get(window)),
    ):
        if estimate and estimate.per_share:
            averages[key] = {
                "value": round(estimate.per_share.value, 2),
                "first_year": estimate.per_share.first_year,
                "last_year": estimate.per_share.last_year,
                "complete": estimate.per_share.complete,
            }

    return {
        "available": True,
        "window": window,
        "years": years,
        "averages": averages,
        "current_price": (
            float(company.current_price) if company.current_price is not None else None
        ),
    }


def _price_at(db, company_id: int, year: int) -> Optional[float]:
    """Цена на дату отчёта за год — как торговалась тогда."""
    from app.models.multiplier import Multiplier

    row = (
        db.query(Multiplier.price_used)
        .filter(
            Multiplier.company_id == company_id,
            Multiplier.type == "report_based",
        )
        .filter(Multiplier.date >= f"{year}-01-01", Multiplier.date <= f"{year}-12-31")
        .first()
    )
    return None if row is None or row[0] is None else float(row[0])


def _epv_band(
    band: ValueBand,
    normal_earnings: dict,
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    book_value_per_share: Optional[float],
    basis: str,
    reason: str,
    payout: Optional[float],
) -> ValueBand:
    """Полоса по EPV — когда формула гл. 32 неприменима.

    Верх берётся по рыночной премии, низ — по премии с надбавкой за риск, так
    же как и в основном пути. Лестницы те же три: EPV делит на ставку, а не на
    `K − g`, и на этом всё различие.
    """
    values, raw_values = [], []
    for name, normal in normal_earnings.items():
        if normal is None or normal <= 0:
            continue
        top = earning_power_value(normal, risk_free_rate, risk_premium)
        if top is None:
            continue
        bottom = earning_power_value(
            normal, risk_free_rate, risk_premium, band.penalty.total
        )
        adjusted, asset_note = asset_adjustment(top, book_value_per_share)
        if name == LADDER_EARNINGS and bottom is not None:
            band.conservative = bottom
        band.ladders.append(Ladder(
            name=name, normal_per_share=round(float(normal), 2),
            multiple=round(top / float(normal), 2),
            value=top, adjusted=adjusted, asset_note=asset_note,
        ))
        values.append(adjusted if adjusted is not None else top)
        raw_values.append(top)
        if bottom is not None:
            raw_values.append(bottom)

    if not values:
        band.refused = True
        # Сюда попадают две разные причины, и различать их обязательно.
        # «Не хватает данных» читается как наша недоработка; отрицательная
        # нормальная прибыль по всем трём лестницам — свойство компании, и
        # никакой метод её не оценит по способности зарабатывать.
        positives = [v for v in normal_earnings.values() if v is not None and v > 0]
        band.reason = reason if positives else (
            "нормальная прибыль отрицательна по всем трём лестницам — "
            "оценивать по способности зарабатывать нечего"
        )
        return band

    band.method = METHOD_EPV
    band.basis = basis
    band.low = round(min(min(values), min(raw_values)), 2)
    band.high = round(max(values), 2)
    band.growth = 0.0
    band.growth_source = "EPV: рост не закладывается"
    band.warnings.append(
        f"{reason}; посчитано по способности зарабатывать (EPV): "
        f"прибыль ÷ требуемая доходность. Рост в такой оценке равен нулю, "
        f"поэтому она — нижняя граница, а не ответ"
        # Приписка только там, где виновата именно выплата: у компании с
        # ростом выше ставки формула ломается по совсем другой причине, и
        # валить на выплату значило бы подсказывать читателю не туда.
        + (f". Выплата {payout}% для формулы главы 32 мала"
           if payout is not None and payout < EPV_PAYOUT_FLOOR else "")
    )
    return band
