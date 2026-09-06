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
from app.services.analysis.valuation_guards import StructureVerdict

# ── Надбавки к премии за риск, процентных пунктов ──────────────────────────
# Величины назначены, а не выведены. Порядок выбран так, чтобы сумма всех
# бед — дёрганая отдача, тонкое покрытие, короткая история — давала около
# пяти пунктов, то есть удваивала рыночную премию. Компания, собравшая всё
# это разом, действительно вдвое рискованнее средней.
PENALTY_SPREAD_MODERATE = 1.0     # коридор отдачи шире образцового
PENALTY_SPREAD_WIDE = 2.0         # коридор сравним с самим уровнем
PENALTY_COVERAGE_FRAGILE = 1.5    # проценты покрыты, но без запаса
PENALTY_HISTORY_SHORT = 1.0       # 5–6 лет
PENALTY_HISTORY_THIN = 2.0        # меньше пяти лет

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

# ── Поправка на активы, гл. 34 ─────────────────────────────────────────────
# Избыток: в счёт идут две трети балансовой стоимости, и к оценке по прибыли
# прибавляется треть разницы (с. 634). Недостаток: зеркально, четверть
# превышения срезается (с. 631).
ASSET_WEIGHT = 2 / 3
EXCESS_SHARE = 1 / 3
SHORTFALL_MULTIPLE = 2.0
SHORTFALL_SHARE = 1 / 4


@dataclass
class RiskPenalty:
    """Надбавка к рыночной премии за то, чего формула сама не видит."""

    spread: float = 0.0
    coverage: float = 0.0
    history: float = 0.0
    notes: list = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(self.spread + self.coverage + self.history, 2)

    def as_dict(self) -> dict:
        return {
            "spread": self.spread,
            "coverage": self.coverage,
            "history": self.history,
            "total": self.total,
            "notes": self.notes,
        }


def risk_penalty(
    stability_label: Optional[str],
    coverage_verdict: Optional[str],
    history_years: Optional[int],
) -> RiskPenalty:
    """Собирает надбавку из трёх измеримых признаков.

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

    if coverage_verdict == "fragile":
        penalty.coverage = PENALTY_COVERAGE_FRAGILE
        penalty.notes.append("проценты покрыты без запаса")

    if history_years is not None:
        if history_years < SHORT_HISTORY_YEARS:
            penalty.history = PENALTY_HISTORY_THIN
            penalty.notes.append(f"история всего {history_years} лет")
        elif history_years < ENOUGH_HISTORY_YEARS:
            penalty.history = PENALTY_HISTORY_SHORT
            penalty.notes.append(f"история {history_years} лет — меньше семи")

    return penalty


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

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "normal_per_share": round(self.normal_per_share, 2),
            "multiple": self.multiple,
            "value": round(self.value, 2),
            "adjusted": self.adjusted,
            "asset_note": self.asset_note,
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
    ladders: list = field(default_factory=list)
    penalty: Optional[RiskPenalty] = None
    basis: str = BASIS_TREND
    multiple_high: Optional[float] = None
    multiple_low: Optional[float] = None
    growth: Optional[float] = None
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
            "width": self.width,
            "asset_lift": self.asset_lift,
            "ladders": [item.as_dict() for item in self.ladders],
            "penalty": self.penalty.as_dict() if self.penalty else None,
            "basis": self.basis,
            "multiple_high": self.multiple_high,
            "multiple_low": self.multiple_low,
            "growth": self.growth,
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

    band.penalty = risk_penalty(stability_label, structure.verdict if structure else None,
                                history_years)

    band.growth = sustainable_growth(roe, payout, growth_cap)
    band.growth_uncapped = sustainable_growth(roe, payout)
    band.growth_capped = growth_is_capped(roe, payout, growth_cap)

    high_multiple = company_multiple(
        payout, roe, risk_free_rate, risk_premium, growth_cap=growth_cap
    )
    low_multiple = company_multiple(
        payout, roe, risk_free_rate, risk_premium, band.penalty.total, growth_cap
    )
    if high_multiple is None or high_multiple.value is None:
        band.refused = True
        band.reason = high_multiple.problem if high_multiple else "не хватает данных"
        return band

    band.multiple_high = high_multiple.value
    band.multiple_low = low_multiple.value if low_multiple else None

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

    values, raw_values = [], []
    for name, normal in normal_earnings.items():
        if normal is None or normal <= 0:
            continue
        raw = high_multiple.value * float(normal)
        adjusted, note = asset_adjustment(raw, book_value_per_share)
        band.ladders.append(Ladder(
            name=name,
            normal_per_share=float(normal),
            multiple=high_multiple.value,
            value=raw,
            adjusted=adjusted,
            asset_note=note,
        ))
        values.append(adjusted if adjusted is not None else raw)
        raw_values.append(raw)

        if band.multiple_low:
            low_raw = band.multiple_low * float(normal)
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
        analyze, buyback_payout, load_points, payout_over_window, stability,
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
    verdict = structure(
        float(latest.operating_profit) if latest and latest.operating_profit is not None else None,
        float(latest.finance_costs) if latest and latest.finance_costs is not None else None,
    )

    # Лестницы: у банка свободный поток не измеряет заработок, поэтому их одна.
    ladders, averages = {}, {}
    for name, estimate in (
        ("прибыль", power.earnings.get(window)),
        ("деньги", power.cash.get(window)),
        ("прибыль владельца", power.owner.get(window)),
    ):
        if estimate is None or estimate.per_share is None:
            continue
        averages[name] = estimate.per_share.value
        # Тренд там, где он определён; иначе средняя. На коротком ряду линию
        # проводить не по чему, и подменять её нечем.
        if basis == BASIS_TREND and estimate.trend is not None:
            ladders[name] = estimate.trend.value
        else:
            ladders[name] = estimate.per_share.value

    backing = power.backing.get(window, {}).get("ratio")
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
