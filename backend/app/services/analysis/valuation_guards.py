"""Ограждения: кому оценку не показывать и какой множитель не красить.

Два правила из пятого издания, оба про то, когда формальная арифметика даёт
число, а смысла в нём нет. Ограждения стоят **до** оценки, а не после:
решить, кому показывать, дешевле, чем чинить показанное.

**Отказ — последнее средство, а не первое.** Раньше низкое покрытие прятало
компанию целиком: ни полосы, ни сигнала, ни объяснения. На данных это вышло в
восемь компаний из сорока пяти, и ответ «ничего не показываем» оказался хуже
ответа «дорого и рискованно, вот насколько». Отказ оставлен там, где оценивать
нечего по существу — проценты платятся при операционном убытке; в остальных
случаях оценка считается, но с крупной надбавкой за риск.

**Финансовые расходы — не тот показатель, которому можно верить в одиночку.**
Величина накопительная и заносится по-разному: где-то нетто (проценты за
вычетом процентного дохода), где-то без лизинговых процентов, где-то с
курсовыми разницами внутри. Перепроверить её по кассе нельзя — «проценты
уплаченные» заполнены у двух компаний из сорока пяти. Поэтому считается
подразумеваемая ставка `финансовые расходы ÷ долг` и сверяется с ключевой:
отклонение в разы означает, что покрытию верить нельзя, и вердикт становится
`unknown`, а не приговором.

**Структура капитала** (гл. 33, с. 613–619). Три компании с одинаковым
капиталом и прибылью до процентов получают множители 11,6 / 12,0 / 6,0 в
зависимости от долга. Умеренный долг слегка повышает множитель — рычаг
поднимает отдачу капитала. Чрезмерный обрушивает его вдвое, и авторы прямо
запрещают применять формальную оценку к таким компаниям: «там, где структура
капитала делает будущее непредсказуемым, число будет ложным» (с. 618). Порог
у них — покрытие процентов: 5,3× приемлемо, 2,0× уже нет.

**Эффект Молодовского** (гл. 34, с. 634). У компании, чья прибыль просела
почти до нуля, множитель взлетает до сотен — не потому, что акция дорога, а
потому, что делят на малое число. Красить такой P/E красным — ошибка чтения:
арифметический артефакт выдаётся за оценку рынка. Правильный ответ — считать
множитель к нормальной прибыли, а не к прибыли провального года.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Покрытие процентов, ниже которого долг перестаёт быть умеренным. У авторов
# 5,3× приемлемо, 2,0× уже нет; граница проведена между ними. Ниже этой черты
# оценка теперь не отменяется, а дорожает — см. вердикт `strained`.
COVERAGE_STRAINED = 2.5
# Выше этого запас прочности по процентам считается спокойным.
COVERAGE_COMFORTABLE = 5.0

# ── Покрытие по средней, а не по году ─────────────────────────────────────
# У Грэма и Додда покрытие процентов — это **средняя прибыль за ряд лет против
# сегодняшних процентов** плюс отдельная проверка худшего года («Анализ
# ценных бумаг», гл. о стандартах надёжности облигаций; «Разумный
# инвестор», гл. 11: средняя за 7 лет и худший год). Один год ничего не
# доказывает ни в какую сторону: у Распадской в 2024 г. операционный убыток
# целиком от неденежного обесценения 18 млрд, а средняя операционная прибыль
# за семь лет покрывает проценты в двадцать раз. Отказ по году назвал бы
# «опасной» компанию без кредитов.
#
# Меньше трёх лет — не ряд, и тогда, как и раньше, судит последний год.
MIN_COVERAGE_YEARS = 3
# Худший год, в котором прибыль не покрыла проценты и одного раза, не даёт
# назвать покрытие спокойным, даже если средняя высокая: авторы проверяют
# его отдельно именно потому, что средняя прячет провалы.
WORST_YEAR_FLOOR = 1.0

# ── Достоверность самих финансовых расходов ────────────────────────────────
# Во сколько раз подразумеваемая ставка (`расходы ÷ долг`) может отличаться от
# ключевой, чтобы цифре ещё можно было верить. Границы широкие намеренно:
# валютный долг честно обходится вдвое дешевле рублёвого, а долг проблемной
# компании — вдвое дороже. Ловится не неточность, а другая величина в поле.
#
# Что этим ловится на деле: у Фосагро подразумеваемая ставка 7,3% против
# ключевой 19,1%, у Норникеля 9,1%, у Базы 8,9%. У Татнефти 102,9% —
# финансовые расходы 36 млрд на долг в 35 млрд, то есть в поле лежит не
# стоимость долга, а что-то ещё.
#
# **Нижняя граница не различает валютный долг и зачтённый процентный доход, и
# не должна.** У Фосагро и Норникеля заём в валюте честно обходится дешевле
# рублёвого, и низкая ставка у них может быть настоящей. Но отличить это от
# нетто-записи по одному числу нельзя, а ошибка в обе стороны опасна
# одинаково: недосчитанные проценты завышают покрытие, то есть делают
# компанию лучше, чем она есть. Поэтому вердикт становится `unknown` —
# «проверить нечем», а не «плохо».
IMPLIED_RATE_FLOOR = 0.5
IMPLIED_RATE_CEILING = 2.5

# Насколько прибыль должна просесть относительно нормальной, чтобы множитель
# перестал что-либо измерять. Половина — уже заметный провал, но множитель
# всего лишь удваивается; артефакт начинается там, где делят на остаток.
MOLODOVSKY_DEPRESSION = 0.4


@dataclass
class StructureVerdict:
    """Позволяет ли структура капитала оценивать компанию формально."""

    coverage: Optional[float]
    verdict: str          # 'ok' | 'fragile' | 'strained' | 'refuse' | 'unknown'
    reason: Optional[str] = None
    # Подразумеваемая ставка и приговор ей: покрытие считается по цифре,
    # которой не всегда можно верить, и читатель должен видеть обе.
    implied_rate: Optional[float] = None
    costs_credible: bool = True
    credibility_note: Optional[str] = None

    @property
    def valuation_allowed(self) -> bool:
        """Отказ — только там, где оценивать нечего по существу.

        Неизвестное покрытие оценку не запрещает: отсутствие данных не то же
        самое, что плохие данные, и молча прятать компанию из-за незаполненного
        поля значило бы врать о ней.

        Тонкое покрытие её тоже больше не запрещает. Прежде запрещало, и это
        было слишком грубо: компания с покрытием 1,04 не «неоценима», она
        дорога в обслуживании долга, и сказать это числом полезнее, чем
        промолчать. Отказ остался за случаем, где проценты платятся при
        операционном убытке: там покрытие отрицательно, и множитель описывает
        не компанию, а деление на знак.
        """
        return self.verdict != "refuse"

    def as_dict(self) -> dict:
        return {
            "coverage": self.coverage,
            "verdict": self.verdict,
            "reason": self.reason,
            "valuation_allowed": self.valuation_allowed,
            "implied_rate": self.implied_rate,
            "costs_credible": self.costs_credible,
            "credibility_note": self.credibility_note,
        }


def interest_coverage(
    operating_profit: Optional[float],
    finance_costs: Optional[float],
    lease_interest: Optional[float] = None,
) -> Optional[float]:
    """Во сколько раз операционная прибыль покрывает проценты.

    `finance_costs` хранится положительным числом. Нулевые проценты означают
    компанию без долга: покрытие бесконечно, и величины у него нет — вместо
    неё возвращается None, а вывод об отсутствии долга делает `structure`.

    **Лизинговые проценты входят в знаменатель.** По МСФО 16 аренда сидит в
    обязательствах, а её процентная часть у многих компаний показана отдельной
    строкой и в финансовые расходы не попадает. Платить её приходится ровно
    так же, как купон, и оставлять за скобками нельзя: у Аэрофлота 18 млрд
    лизинговых процентов против 60 млрд финансовых расходов, и покрытие с ними
    падает с 2,32 до 1,78 — почти на четверть.

    Нашлось это не глазами, а проверкой ставки: 9,8% на долг в 611 млрд при
    ключевой 19,1% — вдвое дешевле рынка, и объяснение оказалось ровно одно.
    """
    if operating_profit is None or finance_costs is None:
        return None
    costs = abs(float(finance_costs))
    if lease_interest is not None:
        costs += abs(float(lease_interest))
    if costs == 0:
        return None
    return round(float(operating_profit) / costs, 2)


def implied_rate(
    finance_costs: Optional[float],
    debt: Optional[float],
) -> Optional[float]:
    """Во сколько обходится долг по этим цифрам, % годовых.

    Грубая величина: долг берётся на конец года, а проценты начислены за год,
    и при быстром наращивании долга ставка выйдет заниженной. Но для того,
    ради чего она считается, точности хватает — отличить стоимость долга от
    случайно попавшей в поле другой величины.
    """
    if finance_costs is None or debt is None:
        return None
    total = float(debt)
    if total <= 0:
        return None
    return round(abs(float(finance_costs)) / total * 100, 2)


def costs_are_credible(
    finance_costs: Optional[float],
    debt: Optional[float],
    key_rate: Optional[float],
) -> tuple:
    """Можно ли верить финансовым расходам. → (можно ли, ставка, пояснение).

    Неизвестное не обвиняется: без долга или без ключевой ставки проверить
    нечем, и цифра считается годной. Отсутствие проверки — не то же самое, что
    провал проверки.
    """
    rate = implied_rate(finance_costs, debt)
    if rate is None or key_rate is None or float(key_rate) <= 0:
        return True, rate, None

    ratio = rate / float(key_rate)
    if ratio < IMPLIED_RATE_FLOOR:
        return False, rate, (
            f"долг обходится в {rate}% при ключевой {float(key_rate):.1f}% — "
            f"втрое дешевле рынка. Похоже, в финансовых расходах зачтён "
            f"процентный доход или не учтена часть обязательств"
        )
    if ratio > IMPLIED_RATE_CEILING:
        return False, rate, (
            f"долг обходится в {rate}% при ключевой {float(key_rate):.1f}% — "
            f"в разы дороже рынка. Похоже, в финансовые расходы попало что-то "
            f"кроме процентов"
        )
    return True, rate, None


def operating_history(reports_by_year: dict, year: int, window: int) -> list:
    """Операционная прибыль за окно, кончающееся годом `year`. → [(год, прибыль)].

    Берутся только годы в валюте последнего отчёта: проценты стоят в ней же,
    и делить доллары прошлого на рубли сегодняшних процентов нельзя.
    """
    latest = reports_by_year.get(year)
    if latest is None:
        return []
    currency = getattr(latest, "currency", None)
    out = []
    for y in range(year - window + 1, year + 1):
        report = reports_by_year.get(y)
        if report is None or getattr(report, "currency", None) != currency:
            continue
        value = getattr(report, "operating_profit", None)
        if value is not None:
            out.append((y, float(value)))
    return out


def net_cash(report) -> Optional[float]:
    """Деньги и краткосрочные вложения за вычетом долга; None, если не из чего."""
    if report is None:
        return None
    debt = getattr(report, "debt", None)
    cash = getattr(report, "cash_and_equivalents", None)
    if debt is None or cash is None:
        return None
    investments = getattr(report, "cash_investments", None) or 0
    return float(cash) + float(investments) - float(debt)


def structure(
    operating_profit: Optional[float],
    finance_costs: Optional[float],
    lease_interest: Optional[float] = None,
    debt: Optional[float] = None,
    key_rate: Optional[float] = None,
    history: Optional[list] = None,
    net_cash: Optional[float] = None,
) -> StructureVerdict:
    """Приговор структуре капитала.

    **Покрытие считается по средней операционной прибыли за окно** (`history`,
    см. `MIN_COVERAGE_YEARS`), проценты — последнего года. Худший год
    проверяется отдельно и не даёт назвать покрытие спокойным.

    **Денег больше долга — долг не бремя.** Компания, которая может погасить
    весь долг из кассы завтра, обслуживает его не из заработка, а из запаса,
    и проверка покрытия к ней неприменима: у Грэма это предельный случай
    финансовой силы, а не риска.

    Отказ — только когда **средняя** операционная прибыль не положительна:
    тогда проценты действительно платятся не из заработка. Убыток одного года
    при положительной средней — худший год, а не приговор.

    Во всех прочих случаях оценка разрешена. Тонкое покрытие превращается в
    вердикт `strained` и в крупную надбавку к премии за риск — см.
    `company_valuation.risk_penalty`.
    """
    if finance_costs is not None and abs(float(finance_costs)) == 0:
        return StructureVerdict(
            coverage=None,
            verdict="ok",
            reason="долга нет — проценты платить нечем и не из чего",
        )

    credible, rate, note = costs_are_credible(finance_costs, debt, key_rate)

    # Средняя за ряд лет вместо одного года, когда ряд есть.
    years = list(history or [])
    averaged = len(years) >= MIN_COVERAGE_YEARS
    earnings = (
        sum(value for _, value in years) / len(years) if averaged else operating_profit
    )
    coverage = interest_coverage(earnings, finance_costs, lease_interest)
    n = len(years)
    word = "года" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "лет"
    period = f"средняя за {n} {word}" if averaged else "последний год"

    # Касса спасает только прибыльное в среднем дело: убыточное проедает её,
    # и завтрашний запас сегодняшним долгом уже не меряется.
    if (
        net_cash is not None and net_cash >= 0
        and debt is not None and float(debt) > 0
        and (earnings is None or float(earnings) > 0)
    ):
        return StructureVerdict(
            coverage=coverage,
            verdict="ok",
            reason=(
                f"денег и краткосрочных вложений больше всего долга (запас "
                f"{net_cash:,.0f} млн сверх него) — долг гасится из кассы, а не "
                f"из заработка, и покрытие процентов здесь не мера риска"
            ).replace(f"{net_cash:,.0f}", f"{net_cash:,.0f}".replace(",", " ")),
            implied_rate=rate, costs_credible=credible, credibility_note=note,
        )

    if coverage is None:
        return StructureVerdict(
            coverage=None,
            verdict="unknown",
            reason="нет операционной прибыли или процентов — покрытие не считается",
            implied_rate=rate, costs_credible=credible, credibility_note=note,
        )

    # Недостоверные расходы делают покрытие непригодным для приговора, но
    # только в сторону смягчения: обвинять компанию по цифре, которой мы сами
    # не верим, нельзя. Хорошее покрытие при недостоверных расходах тоже
    # перестаёт быть заслугой, поэтому вердикт один — `unknown`.
    if not credible and earnings is not None and float(earnings) > 0:
        return StructureVerdict(
            coverage=coverage,
            verdict="unknown",
            reason=note,
            implied_rate=rate, costs_credible=False, credibility_note=note,
        )

    if earnings is not None and float(earnings) <= 0:
        return StructureVerdict(
            coverage=coverage,
            verdict="refuse",
            reason=(
                f"операционный убыток при долге ({period}): покрытие "
                f"{coverage}× — проценты платятся не из прибыли, и формальная "
                f"оценка даст не число, а деление на знак"
            ),
            implied_rate=rate, costs_credible=credible, credibility_note=note,
        )

    # Худший год — отдельная проверка авторов: средняя прячет провалы.
    worst = min(years, key=lambda item: item[1]) if averaged else None
    worst_coverage = (
        None if worst is None
        else interest_coverage(worst[1], finance_costs, lease_interest)
    )
    worst_note = (
        f" В худший год окна ({worst[0]}) покрытие {worst_coverage}×."
        if worst_coverage is not None and worst_coverage < WORST_YEAR_FLOOR else ""
    )

    if coverage < COVERAGE_STRAINED:
        return StructureVerdict(
            coverage=coverage,
            verdict="strained",
            reason=(
                f"проценты покрыты {coverage}× ({period}) при спокойных "
                f"{COVERAGE_COMFORTABLE}× — долг обслуживается почти всей "
                f"операционной прибылью. Оценка считается, но дорожает: "
                f"владельцу от такого дела остаётся мало.{worst_note}"
            ).rstrip(),
            implied_rate=rate, costs_credible=credible, credibility_note=note,
        )

    if coverage >= COVERAGE_COMFORTABLE and worst_note:
        return StructureVerdict(
            coverage=coverage,
            verdict="fragile",
            reason=(
                f"в среднем проценты покрыты {coverage}× ({period}), но средняя "
                f"прячет провал: авторы требуют и спокойной средней, и не "
                f"меньше {WORST_YEAR_FLOOR:g}× в худший год.{worst_note}"
            ),
            implied_rate=rate, costs_credible=credible, credibility_note=note,
        )

    if coverage < COVERAGE_COMFORTABLE:
        return StructureVerdict(
            coverage=coverage,
            verdict="fragile",
            reason=(
                f"проценты покрыты {coverage}× ({period}) — оценка считается, "
                f"но запас невелик: у авторов спокойным считается "
                f"{COVERAGE_COMFORTABLE}× в среднем.{worst_note}"
            ),
            implied_rate=rate, costs_credible=credible, credibility_note=note,
        )

    return StructureVerdict(
        coverage=coverage, verdict="ok",
        reason=f"проценты покрыты {coverage}× ({period})",
        implied_rate=rate, costs_credible=credible, credibility_note=note,
    )


@dataclass
class MolodovskyCheck:
    """Не артефакт ли высокий множитель."""

    reported_multiple: Optional[float]
    normal_multiple: Optional[float]
    depression: Optional[float]   # текущая прибыль ÷ нормальная
    artifact: bool
    reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "reported_multiple": self.reported_multiple,
            "normal_multiple": self.normal_multiple,
            "depression": self.depression,
            "artifact": self.artifact,
            "reason": self.reason,
        }


def molodovsky(
    price: Optional[float],
    current_earnings_per_share: Optional[float],
    normal_earnings_per_share: Optional[float],
) -> MolodovskyCheck:
    """Высокий множитель от провала прибыли — не то же, что дорогая акция.

    Проверка опирается на нормальную прибыль из `earning_power`: только имея
    её, можно отличить «акция дорога» от «год был плохой». Отношение текущей
    прибыли к нормальной и есть мера провала, а множитель к нормальной
    прибыли — то число, которое имеет смысл показывать вместо взлетевшего.

    Убыточный год — предельный случай того же явления: множителя нет вовсе,
    но множитель к нормальной прибыли есть, и он осмыслен.
    """
    reported = None
    if price and current_earnings_per_share and current_earnings_per_share > 0:
        reported = round(float(price) / float(current_earnings_per_share), 2)

    normal = None
    if price and normal_earnings_per_share and normal_earnings_per_share > 0:
        normal = round(float(price) / float(normal_earnings_per_share), 2)

    if normal is None or current_earnings_per_share is None:
        return MolodovskyCheck(reported, normal, None, artifact=False)

    if normal_earnings_per_share is None or normal_earnings_per_share <= 0:
        return MolodovskyCheck(reported, normal, None, artifact=False)

    depression = round(
        float(current_earnings_per_share) / float(normal_earnings_per_share), 3
    )
    if depression >= MOLODOVSKY_DEPRESSION:
        return MolodovskyCheck(reported, normal, depression, artifact=False)

    if depression <= 0:
        reason = (
            f"год убыточный, а нормальная прибыль положительна: множитель к ней "
            f"{normal}. Отсутствие P/E здесь говорит о годе, а не о цене"
        )
    else:
        reason = (
            f"прибыль составила {depression * 100:.0f}% от нормальной, поэтому "
            f"множитель взлетел до {reported}. К нормальной прибыли он {normal} — "
            f"высокий P/E тут артефакт деления, а не дороговизна"
        )
    return MolodovskyCheck(reported, normal, depression, artifact=True, reason=reason)
