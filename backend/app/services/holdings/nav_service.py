"""Оценка холдинга по чистой стоимости активов (NAV).

У холдинга нет собственных операций: выручка и прибыль в его отчётности —
это результаты дочек, консолидированные целиком, хотя акционеру принадлежат
доли. Поэтому P/E и P/B по консолидации показывают чужой бизнес, а рынок
оценивает холдинг иначе — по сумме долей минус долг корпоративного центра,
да ещё с дисконтом за то, что распоряжается активами не акционер.

NAV = Σ (доля × стоимость дочки) + непубличные по оценке − чистый долг центра.

Публичные дочки берутся из карточек, которые уже есть в базе: цена и
количество акций там же, где для всех остальных мультипликаторов.

Незаполненные карточки — норма на этапе набора базы, поэтому расчёт
устроен так, чтобы не врать: доля без цены или без количества акций не
считается нулём, а попадает в список неоценённых, и итог сопровождается
числом «оценено N из M».
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.holding_stake import HoldingStake
from app.services.analysis.share_counts import resolve_shares_for_multipliers

MILLION = 1_000_000.0


@dataclass
class StakeValuation:
    """Одна доля холдинга и её оценка."""

    stake_id: int
    name: str
    ticker: Optional[str] = None
    subsidiary_company_id: Optional[int] = None
    share_pct: float = 0.0
    # Стоимость всей дочки, млн ₽: капитализация с рынка или ручная оценка
    company_value: Optional[float] = None
    # Стоимость доли холдинга, млн ₽
    stake_value: Optional[float] = None
    source: str = "unknown"  # 'market' | 'manual' | 'unknown'
    missing: Optional[str] = None  # чего не хватает, если оценить не удалось


@dataclass
class HoldingNav:
    """Итог оценки холдинга."""

    company_id: int
    stakes: List[StakeValuation] = field(default_factory=list)
    stakes_value: Optional[float] = None          # сумма оценённых долей, млн ₽
    corporate_center_net_debt: Optional[float] = None
    nav: Optional[float] = None                   # млн ₽
    market_cap: Optional[float] = None            # млн ₽
    discount_pct: Optional[float] = None          # (1 − кап/NAV) × 100
    valued_stakes: int = 0
    total_stakes: int = 0


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_shares(db: Session, company_id: int) -> Optional[int]:
    """Количество акций из свежайшего отчёта — та же база, что у капитализации."""
    report = (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .order_by(FinancialReport.report_date.desc())
        .first()
    )
    if report is None:
        return None
    return resolve_shares_for_multipliers(report)


def market_cap_mln(db: Session, company: Company) -> tuple[Optional[float], Optional[str]]:
    """Капитализация компании в млн ₽ и причина, если посчитать не вышло."""
    price = _num(company.current_price)
    if price is None:
        return None, "нет текущей цены"

    shares = _latest_shares(db, company.id)
    if shares is None:
        return None, "нет количества акций в отчётах"

    return round(price * shares / MILLION, 3), None


def _value_stake(db: Session, stake: HoldingStake) -> StakeValuation:
    share_pct = _num(stake.share_pct) or 0.0
    result = StakeValuation(
        stake_id=stake.id,
        name=stake.name,
        subsidiary_company_id=stake.subsidiary_company_id,
        share_pct=share_pct,
    )

    # Ручная оценка сильнее: её ставят там, где рынка нет (непубличный актив)
    # либо когда котировка заведомо не отражает стоимость.
    manual = _num(stake.manual_valuation)
    if manual is not None:
        result.company_value = manual
        result.stake_value = round(manual * share_pct / 100, 3)
        result.source = "manual"
        return result

    subsidiary = stake.subsidiary
    if subsidiary is None:
        result.missing = "нет ни ссылки на карточку, ни ручной оценки"
        return result

    result.ticker = subsidiary.ticker
    cap, missing = market_cap_mln(db, subsidiary)
    if cap is None:
        result.missing = missing
        return result

    result.company_value = cap
    result.stake_value = round(cap * share_pct / 100, 3)
    result.source = "market"
    return result


def compute_holding_nav(db: Session, company_id: int) -> Optional[HoldingNav]:
    """Считает NAV холдинга и дисконт капитализации к нему.

    Returns:
        None, если компании нет. Пустой список долей — не ошибка: холдинг
        только что заведён, и интерфейс покажет приглашение их добавить.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return None

    stakes = (
        db.query(HoldingStake)
        .filter(HoldingStake.holding_company_id == company_id)
        .order_by(HoldingStake.id)
        .all()
    )

    valuations = [_value_stake(db, stake) for stake in stakes]
    valued = [v for v in valuations if v.stake_value is not None]

    nav_result = HoldingNav(
        company_id=company_id,
        stakes=valuations,
        total_stakes=len(valuations),
        valued_stakes=len(valued),
        corporate_center_net_debt=_num(company.corporate_center_net_debt),
    )

    if valued:
        nav_result.stakes_value = round(sum(v.stake_value or 0.0 for v in valued), 3)

    if nav_result.stakes_value is not None:
        debt = nav_result.corporate_center_net_debt or 0.0
        nav_result.nav = round(nav_result.stakes_value - debt, 3)

    cap, _missing = market_cap_mln(db, company)
    nav_result.market_cap = cap

    # Дисконт имеет смысл только при положительном NAV: при отрицательном
    # (долг центра больше стоимости долей) сравнивать не с чем.
    if cap is not None and nav_result.nav is not None and nav_result.nav > 0:
        nav_result.discount_pct = round((1 - cap / nav_result.nav) * 100, 2)

    return nav_result
