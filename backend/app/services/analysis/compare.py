"""Сравнение компаний одной отрасли — по образцу гл. 18 «Разумного инвестора».

Грэм ставил рядом две компании и сводил в одну таблицу цену, масштаб, прибыль
за три точки времени, дивиденды, коэффициенты и рост, а потом писал
комментарий. Здесь то же, плюс то, что считает проект: свободный поток,
отдача сверх ставки, опорная стоимость, запас прочности, консервативные
критерии.

**Комментарий не хранится и не пишется руками.** Он собирается по правилам
из тех же чисел, что в таблице, при каждом запросе: добавился отчёт или
сдвинулась цена — изменились числа, а за ними и фразы. Правила только
описывают различия («дешевле по прибыли», «отдача ниже ставки»), советов
в них нет.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.enums import PeriodType
from app.models.financial_report import FinancialReport
from app.models.multiplier import Multiplier
from app.services.analysis import multiplier_service, screen, screen_axes
from app.services.analysis.market_snapshot import trustworthy_tickers
from app.services.share_splits import company_splits, current_share_count, report_split_factor
from app.utils.currency_converter import convert_to_rub

MAX_PICK = 5

# Отрасль для подписи: сектор справочника плюс отраслевой профиль. Сектор
# один не годится — в «энергетике» рядом нефтяники и генерация, — профиль
# тоже: «добыча и металлы» объединяет нефть с золотом.
GROUP_LABEL = {
    ("energy", "oil_gas_mining"): "нефть и газ",
    ("materials", "oil_gas_mining"): "металлы и добыча",
    ("consumer", "retail_general"): "потребительский сектор",
    ("consumer", "retail_grocery"): "продуктовая розница",
    ("financial", "bank"): "банки",
    ("financial", "exchange"): "биржи",
    ("industrials", "industrial"): "промышленность",
    ("it", "it_telecom"): "технологии",
    ("telecom", "it_telecom"): "связь",
    ("real_estate", "developer"): "девелоперы",
    ("utilities", "utilities"): "электроэнергетика",
}

SECTION_ORDER = ("size", "financial", "stability", "dividends", "growth", "price", "profitability")


def group_key(db: Session, company: Company) -> tuple[str, str]:
    return (str(company.sector or ""), screen.profile_for(db, company).key)


def group_label(key: tuple[str, str]) -> str:
    return GROUP_LABEL.get(key, key[0] or "без отрасли")


def peers(db: Session, company: Company) -> list[Company]:
    """Проверенные компании той же отрасли, крупные первыми. Если в узкой
    группе (сектор + профиль) соседей меньше двух — берём весь сектор."""
    trusted = [db.query(Company).filter(Company.ticker == t).first() for t in trustworthy_tickers(db)]
    trusted = [c for c in trusted if c is not None]
    key = group_key(db, company)
    same = [c for c in trusted if group_key(db, c) == key]
    if len([c for c in same if c.id != company.id]) < 2:
        same = [c for c in trusted if c.sector == company.sector]
    return sorted(same, key=lambda c: -(_market_cap(db, c) or 0))


def _market_cap(db: Session, company: Company) -> Optional[float]:
    row = (
        db.query(Multiplier.market_cap)
        .filter(Multiplier.company_id == company.id, Multiplier.market_cap.isnot(None))
        .order_by(Multiplier.date.desc())
        .first()
    )
    return float(row[0]) if row else None


def _rub(value: Optional[float], report: Optional[FinancialReport]) -> Optional[float]:
    if value is None or report is None:
        return value
    rate = float(report.exchange_rate) if report.exchange_rate else None
    return convert_to_rub(float(value), report.currency or "RUB", rate)


def _eps_by_year(db: Session, company: Company) -> dict[int, float]:
    """Прибыль на акцию по годовым отчётам — в сегодняшней шкале акций."""
    splits = company_splits(db, company)
    current = current_share_count(db, company.id, splits)
    out = {}
    rows = (
        db.query(Multiplier, FinancialReport)
        .join(FinancialReport, Multiplier.report_id == FinancialReport.id)
        .filter(Multiplier.company_id == company.id, Multiplier.type == "report_based",
                FinancialReport.period_type == PeriodType.ANNUAL)
        .all()
    )
    for mult, report in rows:
        if mult.eps is None:
            continue
        scale = report_split_factor(splits, mult.date, float(mult.shares_used) if mult.shares_used else None, current)
        out[int(report.fiscal_year)] = float(mult.eps) / scale
    return out


def _axis_value(axes: list, axis: str, key: str) -> Optional[float]:
    a = next((x for x in axes if x.key == axis), None)
    m = a.metric(key) if a is not None else None
    return None if m is None else m.value


def company_card(db: Session, company: Company, summary_fn) -> dict:
    """Все числа одной компании для таблицы сравнения."""
    current = multiplier_service.calculate_current_multipliers(db=db, company_id=company.id) or {}
    balance = db.get(FinancialReport, current.get("balance_report_id")) if current.get("balance_report_id") else None
    axes = screen_axes.load(db, company)
    profile = screen.profile_for(db, company)
    result = screen.apply(axes, profile, "defensive", ticker=str(company.ticker))
    sections: dict[str, Optional[bool]] = {}
    for v in result.verdicts:
        if v.status == screen.NOT_APPLICABLE:
            continue
        ok = v.status == screen.PASS
        sections[v.axis] = ok if sections.get(v.axis, True) else False
    try:
        summary = summary_fn(company.id)
    except Exception:  # noqa: BLE001 — оценки может не быть: таблица без неё всё равно нужна
        summary = {}
    safety = (summary or {}).get("safety") or {}

    eps = _eps_by_year(db, company)
    last_year = max(eps) if eps else None
    shares = current.get("shares_used")
    equity = _rub(current.get("equity"), balance)
    return {
        "id": company.id,
        "ticker": company.ticker,
        "name": company.name,
        "logo_url": company.brand_logo_url,
        "is_bank": profile.key in ("bank",),
        "price": current.get("current_price"),
        "shares": shares,
        "market_cap": current.get("market_cap"),
        "net_debt": _rub(current.get("net_debt"), balance),
        "book_per_share": (equity * 1e6 / shares) if equity and shares else None,
        "revenue": _rub(current.get("ltm_revenue"), balance),
        "net_income": _rub(current.get("ltm_net_income"), balance),
        "fcf": _rub(current.get("ltm_fcf"), balance),
        "eps": current.get("eps"),
        "eps_years": {str(y): eps.get(y) for y in ([last_year, last_year - 5, last_year - 10] if last_year else [])},
        "dividend": current.get("ltm_dividends_per_share"),
        "streak": _axis_value(axes, "dividends", "streak"),
        "pe": current.get("pe_ratio"),
        "pb": current.get("pb_ratio"),
        "p_fcf": current.get("price_to_fcf"),
        "dividend_yield": current.get("dividend_yield"),
        "net_margin": _axis_value(axes, "profitability", "net_margin"),
        "roe": current.get("roe"),
        "roe_spread": current.get("roe_spread"),
        "key_rate": current.get("key_rate"),
        "current_ratio": current.get("current_ratio"),
        "debt_to_equity": current.get("debt_to_equity"),
        "growth_10": _axis_value(axes, "growth", "earnings_growth"),
        "growth_5": _axis_value(axes, "growth", "earnings_growth_short"),
        "profitable_years": _axis_value(axes, "stability", "profitable_years"),
        "reference": safety.get("reference"),
        "margin": safety.get("value_margin"),
        "sections": {k: sections.get(k) for k in SECTION_ORDER if k in sections},
    }


# ── Комментарий ─────────────────────────────────────────────────────────────

def _ru(x: float, digits: int = 1) -> str:
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",").replace("-", "−")


def _b(card: dict) -> str:
    return f"**{card['name']}**"


def _list(cards: list[dict]) -> str:
    names = [_b(c) for c in cards]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " и " + names[-1]


def _extreme(cards: list[dict], key: str, lowest: bool) -> Optional[dict]:
    known = [c for c in cards if c.get(key) is not None]
    if len(known) < 2:
        return None
    return (min if lowest else max)(known, key=lambda c: c[key])


def comment(cards: list[dict]) -> list[str]:
    """Абзацы комментария. Каждая фраза — следствие чисел таблицы."""
    out: list[str] = []
    if len(cards) < 2:
        return out

    # Цена: по прибыли и по балансу.
    cheap_pe = _extreme([c for c in cards if (c.get("pe") or 0) > 0], "pe", True)
    dear_pe = _extreme([c for c in cards if (c.get("pe") or 0) > 0], "pe", False)
    if cheap_pe and dear_pe and dear_pe["pe"] >= cheap_pe["pe"] * 1.15:
        out.append(f"Дешевле всех по прибыли {_b(cheap_pe)} — {_ru(cheap_pe['pe'])} годовой прибыли за акцию; "
                   f"дороже всех {_b(dear_pe)} — {_ru(dear_pe['pe'])}.")
    elif cheap_pe and dear_pe:
        out.append(f"По прибыли все стоят почти одинаково: от {_ru(cheap_pe['pe'])} до {_ru(dear_pe['pe'])} годовой прибыли.")

    cheap_pb = _extreme([c for c in cards if (c.get("pb") or 0) > 0], "pb", True)
    if cheap_pb and cheap_pb.get("roe") is not None:
        line = f"Дешевле всех по балансу {_b(cheap_pb)} — {_ru(cheap_pb['pb'], 2)} капитала"
        if cheap_pb.get("roe_spread") is not None and cheap_pb["roe_spread"] < 0:
            line += (f", но отдача на капитал лишь {_ru(cheap_pb['roe'])}% — меньше ключевой ставки. "
                     "Дешевизна по балансу здесь объясняется отдачей, а не скидкой.")
        else:
            line += f" при отдаче на капитал {_ru(cheap_pb['roe'])}%."
        out.append(line)

    # Отдача.
    best_roe = _extreme(cards, "roe", False)
    below = [c for c in cards if c.get("roe_spread") is not None and c["roe_spread"] < 0 and c is not cheap_pb]
    if best_roe:
        line = f"Больше всех зарабатывает на капитал {_b(best_roe)} — {_ru(best_roe['roe'])}%."
        if below:
            line += f" Ниже ключевой ставки отдача у {_list(below)}."
        out.append(line)

    # Дивиденды.
    best_dy = _extreme(cards, "dividend_yield", False)
    longest = _extreme(cards, "streak", False)
    if best_dy and best_dy["dividend_yield"]:
        line = f"Выше всех дивидендная доходность у {_b(best_dy)} — {_ru(best_dy['dividend_yield'])}%"
        if longest and longest["streak"]:
            line += (f"; дольше всех платит без перерыва {_b(longest)} — {_ru(longest['streak'], 0)} лет подряд."
                     if longest is not best_dy else f", и платит дольше всех — {_ru(longest['streak'], 0)} лет подряд.")
        else:
            line += "."
        out.append(line)

    # Баланс.
    net_cash = [c for c in cards if c.get("net_debt") is not None and c["net_debt"] < 0]
    heavy = [c for c in cards if not c.get("is_bank") and (c.get("debt_to_equity") or 0) > 1]
    tight = [c for c in cards if not c.get("is_bank") and c.get("current_ratio") is not None and c["current_ratio"] < 1]
    parts = []
    if net_cash:
        parts.append(f"денег больше, чем долга, у {_list(net_cash)}")
    if heavy:
        parts.append(f"обязательств больше капитала у {_list(heavy)}")
    if tight:
        parts.append(f"оборотных активов меньше краткосрочных обязательств у {_list(tight)}")
    if parts:
        text = "; ".join(parts) + "."
        out.append(text[0].upper() + text[1:])

    # Рост.
    fast = _extreme(cards, "growth_5", False)
    falling = [c for c in cards if c.get("growth_5") is not None and c["growth_5"] < 0]
    if fast and fast["growth_5"] > 0:
        line = f"Быстрее всех за пять лет растила прибыль на акцию {_b(fast)} — +{_ru(fast['growth_5'], 0)}%."
        if falling:
            line += f" Снизилась прибыль у {_list(falling)}."
        out.append(line)

    # Консервативные критерии.
    full = [c for c in cards if c["sections"] and all(c["sections"].values())]
    partial = [c for c in cards if c["sections"] and not all(c["sections"].values())]
    names = {"size": "размер", "financial": "финансовое положение", "stability": "стабильность",
             "dividends": "дивиденды", "growth": "рост", "price": "цена", "profitability": "рентабельность"}
    if full:
        out.append(f"Все разделы свода защитного инвестора проходит {_list(full)}." if len(full) == 1
                   else f"Все разделы свода защитного инвестора проходят {_list(full)}.")
    for c in partial:
        failed = [names[k] for k, ok in c["sections"].items() if ok is False]
        if failed:
            out.append(f"{_b(c)} не проходит: {', '.join(failed)}.")

    # Оценка.
    below_ref = [c for c in cards if c.get("margin") is not None and c["margin"] > 0]
    priced = [c for c in cards if c.get("margin") is not None]
    if priced and not below_ref:
        out.append("Все сейчас дороже опорной оценки." if len(priced) == len(cards)
                   else f"Дороже опорной оценки — {_list(priced)}.")
    elif below_ref:
        best = max(below_ref, key=lambda c: c["margin"])
        out.append(f"Ниже опорной оценки торгуется {_list(below_ref)}; наибольший запас — у {_b(best)}, "
                   f"{_ru(best['margin'] * 100, 0)}%.")
    return out


def build(db: Session, companies: list[Company], summary_fn) -> dict:
    cards = [company_card(db, c, summary_fn) for c in companies]
    key = group_key(db, companies[0]) if companies else ("", "")
    return {
        "as_of": date.today().isoformat(),
        "group": group_label(key),
        "group_size": len(peers(db, companies[0])) if companies else 0,
        "companies": cards,
        "comment": comment(cards),
    }
