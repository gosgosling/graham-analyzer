"""Ограждения: кому оценку не показывать и какой множитель не красить.

Два правила из пятого издания, оба про то, когда формальная арифметика даёт
число, а смысла в нём нет. Ограждения стоят **до** оценки, а не после:
решить, кому показывать, дешевле, чем чинить показанное.

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

# Покрытие процентов, ниже которого формальная оценка не показывается вовсе.
# У авторов 5,3× приемлемо, 2,0× уже нет; граница проведена между ними.
COVERAGE_REFUSE = 2.5
# Выше этого запас прочности по процентам считается спокойным.
COVERAGE_COMFORTABLE = 5.0

# Насколько прибыль должна просесть относительно нормальной, чтобы множитель
# перестал что-либо измерять. Половина — уже заметный провал, но множитель
# всего лишь удваивается; артефакт начинается там, где делят на остаток.
MOLODOVSKY_DEPRESSION = 0.4


@dataclass
class StructureVerdict:
    """Позволяет ли структура капитала оценивать компанию формально."""

    coverage: Optional[float]
    verdict: str          # 'ok' | 'fragile' | 'refuse' | 'unknown'
    reason: Optional[str] = None

    @property
    def valuation_allowed(self) -> bool:
        """Отказ — только при доказанной нехватке покрытия.

        Неизвестное покрытие оценку не запрещает: отсутствие данных не то же
        самое, что плохие данные, и молча прятать компанию из-за незаполненного
        поля значило бы врать о ней.
        """
        return self.verdict != "refuse"

    def as_dict(self) -> dict:
        return {
            "coverage": self.coverage,
            "verdict": self.verdict,
            "reason": self.reason,
            "valuation_allowed": self.valuation_allowed,
        }


def interest_coverage(
    operating_profit: Optional[float],
    finance_costs: Optional[float],
) -> Optional[float]:
    """Во сколько раз операционная прибыль покрывает проценты.

    `finance_costs` хранится положительным числом. Нулевые проценты означают
    компанию без долга: покрытие бесконечно, и величины у него нет — вместо
    неё возвращается None, а вывод об отсутствии долга делает `structure`.
    """
    if operating_profit is None or finance_costs is None:
        return None
    costs = abs(float(finance_costs))
    if costs == 0:
        return None
    return round(float(operating_profit) / costs, 2)


def structure(
    operating_profit: Optional[float],
    finance_costs: Optional[float],
) -> StructureVerdict:
    """Приговор структуре капитала.

    Убыток при наличии долга — отказ независимо от размера долга: покрытие
    отрицательное, и проценты платятся не из прибыли.
    """
    if finance_costs is not None and abs(float(finance_costs)) == 0:
        return StructureVerdict(
            coverage=None,
            verdict="ok",
            reason="долга нет — проценты платить нечем и не из чего",
        )

    coverage = interest_coverage(operating_profit, finance_costs)
    if coverage is None:
        return StructureVerdict(
            coverage=None,
            verdict="unknown",
            reason="нет операционной прибыли или процентов — покрытие не считается",
        )

    if coverage < COVERAGE_REFUSE:
        return StructureVerdict(
            coverage=coverage,
            verdict="refuse",
            reason=(
                f"проценты покрыты {coverage}× при пороге {COVERAGE_REFUSE}× — "
                f"структура капитала делает будущее непредсказуемым, и формальная "
                f"оценка даст ложное число"
            ),
        )

    if coverage < COVERAGE_COMFORTABLE:
        return StructureVerdict(
            coverage=coverage,
            verdict="fragile",
            reason=(
                f"проценты покрыты {coverage}× — оценка считается, но запас "
                f"невелик: у авторов спокойным считается {COVERAGE_COMFORTABLE}×"
            ),
        )

    return StructureVerdict(coverage=coverage, verdict="ok")


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
