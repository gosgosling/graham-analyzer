"""Базовый множитель рынка: `payout / (K − g)`.

Это модель Гордона, повёрнутая так, чтобы отвечать на вопрос «какой P/E
оправдан», а не «какая цена справедлива». Вывод занимает три строки. Акция
приносит владельцу дивиденды и ничего больше, так что её цена — сумма всех
будущих выплат, приведённых к сегодня:

    P = D/(1+K) + D(1+g)/(1+K)² + D(1+g)²/(1+K)³ + …  =  D / (K − g)

Делим на прибыль: слева P/E, справа D/E — то есть доля прибыли, уходящая на
дивиденды. Отсюда `множитель = payout / (K − g)`.

Из вывода следует то, что иначе выглядит произволом. Требование `K > g` — не
техническая оговорка: при `g ≥ K` каждое следующее слагаемое больше
предыдущего, сумма бесконечна, а экономически это значит «компания растёт
быстрее экономики вечно», то есть однажды становится всей экономикой.
Зависимость ответа от разности `K − g` — просто деление на малое число.

**У формулы есть слабое место, о котором книга умалчивает.** С `payout` и `g`
она обращается как с независимыми величинами, а они связаны: компания растёт
на то, что не раздала. Отсюда устойчивый рост `g = ROE × (1 − payout)`, и
угадывать его не нужно — см. `sustainable_growth`.

Коттл–Мюррей–Блок, гл. 32, с. 605–606. Расчёт авторов для S&P 400 на 1987 год:

    ставка облигаций Aaa       8,50%
    премия за риск             2,75%
    K = ожидаемая доходность  11,25%
    рост дивидендов g          7,50%
    payout                       46%

    Множитель = 0,46 / (0,1125 − 0,0750) = 12,27

Величина устроена так, что почти целиком определяется **разностью** `K − g`.
При K − g = 3,75 п.п. множитель 12,3; при 5 п.п. — уже 9,2; при 2 п.п. — 23.
Отсюда два следствия, важнее самой формулы:

1. Множитель рынка — про ставки, а не про качество компаний. Средние за
   эпохи у авторов: 1947–1957 — 10,1; 1958–1972 — 17,6; 1973–1985 — 10,1.
   Разброс вдвое объясняется режимом ставок.
2. Когда `K − g` мала, ответ разлетается от крошечных изменений входа.
   Такой множитель показывать нельзя — не потому, что он велик, а потому,
   что он ничего не измеряет.

Исторический якорь США: средний множитель за 115 лет (1871–1985) — **13,8**,
диапазон средних за пятилетия от 8,9 до 18,8. Это справка, а не проверка:
при российских ставках формула честно даёт величину втрое меньше, и
подгонять её под чужой диапазон значило бы выбросить единственное, что
формула умеет — реагировать на ставку.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Ниже этого зазора между требуемой доходностью и ростом ответ определяется
# уже не рынком, а погрешностью входных величин.
MIN_SPREAD = 1.0
# Зазор, при котором ответ ещё устойчив, но чувствительность стоит показать.
FRAGILE_SPREAD = 2.5

# Справочные величины из книги (США, 1871–1985). Только для сравнения.
HISTORIC_AVERAGE = 13.8
HISTORIC_RANGE = (8.9, 18.8)

# Пример из книги — держим рядом с формулой как исполняемую проверку смысла.
SP400_1987 = {
    "risk_free_rate": 8.5,
    "risk_premium": 2.75,
    "dividend_growth": 7.5,
    "payout": 46.0,
}


@dataclass
class BaseMultiple:
    """Базовый множитель вместе с тем, из чего он сложился."""

    payout: float
    risk_free_rate: float
    risk_premium: float
    dividend_growth: float
    value: Optional[float] = None
    problem: Optional[str] = None

    @property
    def required_return(self) -> float:
        """K — ожидаемая доходность вложения в акции."""
        return round(self.risk_free_rate + self.risk_premium, 4)

    @property
    def spread(self) -> float:
        """K − g. Всё поведение множителя определяется этой разностью."""
        return round(self.required_return - self.dividend_growth, 4)

    @property
    def fragile(self) -> bool:
        """Зазор мал: ответ чувствителен к входу сильнее, чем к рынку."""
        return self.value is not None and self.spread < FRAGILE_SPREAD

    @property
    def earnings_yield(self) -> Optional[float]:
        """Обратная величина, %. Читается проще множителя."""
        if not self.value:
            return None
        return round(100.0 / self.value, 2)

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "problem": self.problem,
            "payout": self.payout,
            "risk_free_rate": self.risk_free_rate,
            "risk_premium": self.risk_premium,
            "dividend_growth": self.dividend_growth,
            "required_return": self.required_return,
            "spread": self.spread,
            "fragile": self.fragile,
            "earnings_yield": self.earnings_yield,
            "historic_average": HISTORIC_AVERAGE,
            "historic_range": list(HISTORIC_RANGE),
        }


def base_multiple(
    payout: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    dividend_growth: Optional[float],
) -> Optional[BaseMultiple]:
    """Множитель рынка по формуле гл. 32. Все доли — в процентах.

    Отказ считать оформляется через `problem`, а не через пустой результат:
    пользователю нужно знать, что оценка не выведена **и почему**, иначе
    пустая клетка прочитается как отсутствие данных.
    """
    if None in (payout, risk_free_rate, risk_premium, dividend_growth):
        return None

    result = BaseMultiple(
        payout=float(payout),
        risk_free_rate=float(risk_free_rate),
        risk_premium=float(risk_premium),
        dividend_growth=float(dividend_growth),
    )

    if result.payout <= 0:
        result.problem = (
            "рынок не платит дивидендов — формула через выплату неприменима"
        )
        return result

    if result.spread <= 0:
        result.problem = (
            f"рост дивидендов {result.dividend_growth}% не ниже требуемой "
            f"доходности {result.required_return}% — формула даёт бесконечность"
        )
        return result

    if result.spread < MIN_SPREAD:
        result.problem = (
            f"зазор между требуемой доходностью и ростом {result.spread} п.п. — "
            f"ответ определяется погрешностью входа, а не рынком"
        )
        return result

    result.value = round(result.payout / result.spread, 2)
    return result


def sensitivity(
    multiple: BaseMultiple,
    steps: tuple = (-1.0, -0.5, 0.5, 1.0),
) -> list:
    """Как ответ поедет от сдвига премии за риск на доли пункта.

    Показывать обязательно. Премия за риск — самая произвольная из входных
    величин, и читатель должен видеть цену этого произвола, а не одно число,
    выглядящее как измерение.
    """
    if multiple.value is None:
        return []
    rows = []
    for step in steps:
        shifted = base_multiple(
            multiple.payout,
            multiple.risk_free_rate,
            multiple.risk_premium + step,
            multiple.dividend_growth,
        )
        rows.append({
            "risk_premium_shift": step,
            "risk_premium": round(multiple.risk_premium + step, 2),
            "value": None if shifted is None else shifted.value,
            "problem": None if shifted is None else shifted.problem,
        })
    return rows


@dataclass
class ObservedPayout:
    """Доля прибыли на дивиденды, посчитанная по базе."""

    payout: Optional[float]
    companies: int
    total_dividends: float
    total_profit: float

    def as_dict(self) -> dict:
        return {
            "payout": self.payout,
            "companies": self.companies,
            "total_dividends": round(self.total_dividends, 1),
            "total_profit": round(self.total_profit, 1),
        }


def observed_payout(pairs) -> ObservedPayout:
    """Совокупная выплата: сумма дивидендов ÷ сумма прибыли.

    Именно совокупная, а не средняя по компаниям: множитель считается для
    рынка, а рынок — это взвешенная сумма, где Сбербанк весит больше
    Ленэнерго. Средняя по компаниям отвечала бы на другой вопрос — «сколько
    платит типичная компания».

    Убыточные годы из знаменателя не выбрасываются. Убыток — часть того, что
    рынок заработал, и выбрасывать его значит завышать выплату ровно так же,
    как нормализация прибыли завышает среднюю.

    `pairs` — последовательность (дивиденды, прибыль) в одинаковых единицах.
    """
    usable = [(d, p) for d, p in pairs if d is not None and p is not None]
    total_dividends = sum(d for d, _ in usable)
    total_profit = sum(p for _, p in usable)

    payout = None
    if total_profit > 0:
        payout = round(total_dividends / total_profit * 100.0, 2)

    return ObservedPayout(
        payout=payout,
        companies=len(usable),
        total_dividends=total_dividends,
        total_profit=total_profit,
    )


def implied_growth(
    payout: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    observed_multiple: Optional[float],
) -> Optional[float]:
    """Какой рост дивидендов заложен в цену рынка, %.

    Формула развёрнута: `g = K − payout / множитель`. Из четырёх величин темп
    роста — самая произвольная, и вместо того чтобы назначить его и потом
    удивляться расхождению с ценой, честнее спросить, какой рост рынок уже
    закладывает, и решить, согласны ли мы с ним.

    Величина номинальная, как и `K`: доходность ОФЗ содержит инфляционные
    ожидания, и сравнивать её с реальным ростом нельзя. Здесь легче всего
    ошибиться — смешать номинальную ставку с реальным ростом и получить
    множитель вдвое не тот.
    """
    if None in (payout, risk_free_rate, risk_premium, observed_multiple):
        return None
    if not observed_multiple or observed_multiple <= 0 or payout <= 0:
        return None
    required = float(risk_free_rate) + float(risk_premium)
    return round(required - float(payout) / float(observed_multiple), 2)


def implied_premium(
    payout: Optional[float],
    risk_free_rate: Optional[float],
    dividend_growth: Optional[float],
    observed_multiple: Optional[float],
) -> Optional[float]:
    """Какая премия за риск заложена в цену, п.п.

    Зеркало `implied_growth`: `премия = payout / множитель + g − ставка`.
    Отрицательная величина означает, что при заданном росте рынок оценивает
    акции дешевле безрисковой бумаги, — то есть либо рост завышен, либо в
    цене сидит нечто, чего в модели нет.
    """
    if None in (payout, risk_free_rate, dividend_growth, observed_multiple):
        return None
    if not observed_multiple or observed_multiple <= 0 or payout <= 0:
        return None
    return round(
        float(payout) / float(observed_multiple)
        + float(dividend_growth)
        - float(risk_free_rate),
        2,
    )


def sustainable_growth(
    roe: Optional[float],
    payout: Optional[float],
) -> Optional[float]:
    """Темп роста, который компания способна обеспечить сама: `ROE × (1 − payout)`.

    Формула множителя принимает `payout` и `g` за независимые величины, но
    расти можно только на то, что не раздал: раздал всё — источника роста не
    осталось. Поэтому `g` не назначается суждением, а выводится из отдачи на
    капитал и доли выплаты.

    Величина номинальная, как и ROE. При инфляции 7% и номинальном росте 6,4%
    реальный рост отрицателен — и это надо видеть, а не прятать за
    правдоподобно выглядящим числом.

    Выплата выше ста процентов (раздали больше, чем заработали) даёт
    отрицательный рост. Это не ошибка: компания проедает капитал, и на длинном
    горизонте дивиденды обязаны снижаться.
    """
    if roe is None or payout is None:
        return None
    return round(float(roe) * (1.0 - float(payout) / 100.0), 2)


def paired_multiples(
    payout: Optional[float],
    risk_free_rate: Optional[float],
    risk_premium: Optional[float],
    dividend_growth: Optional[float],
    normalized_risk_free_rate: Optional[float] = None,
) -> dict:
    """Множитель при сегодняшней ставке и при нормализованной.

    `K` в формуле — доходность на бесконечность, то есть подставляя текущую
    ставку, мы объявляем её вечной. Когда кривая на многолетних максимумах,
    это занижает множитель вдвое, и разница говорит о моменте, а не о
    компаниях. Одно число здесь врало бы независимо от того, какое выбрать,
    поэтому возвращаются оба.
    """
    current = base_multiple(payout, risk_free_rate, risk_premium, dividend_growth)
    normalized = None
    if normalized_risk_free_rate is not None:
        normalized = base_multiple(
            payout, normalized_risk_free_rate, risk_premium, dividend_growth
        )

    gap = None
    if (current is not None and current.value
            and normalized is not None and normalized.value):
        gap = round(normalized.value / current.value, 2)

    return {
        "current": current,
        "normalized": normalized,
        # Во сколько раз множитель вырастет, если ставки вернутся к норме.
        "rate_effect": gap,
    }
