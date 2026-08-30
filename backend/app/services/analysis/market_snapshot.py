"""Снимок рынка: выплата, отдача на капитал и фактический множитель.

Все величины считаются **только по компаниям, за которые можно ручаться** —
помеченным проверенными и прошедшим аудит без дефектов. Считать выплату
рынка по всей базе бессмысленно: у большинства компаний половина полей пуста,
и сумма получится не про рынок, а про то, что успели заполнить.

Величины совокупные, а не средние по компаниям. Множитель считается для
рынка, а рынок — взвешенная сумма, где Сбербанк весит больше Ленэнерго.
Средняя по компаниям отвечала бы на другой вопрос: «сколько платит типичная
компания».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.analysis.data_audit import collect
from app.services.analysis.market_multiple import observed_payout, sustainable_growth

# Год, за который берутся выплата и отдача: последний полностью закрытый.
DEFAULT_YEAR = 2024


@dataclass
class MarketSnapshot:
    """Что рынок показывает сам, без единого допущения."""

    year: int
    tickers: list
    companies: int
    payout: Optional[float]
    roe: Optional[float]
    growth: Optional[float]
    total_dividends: float
    total_profit: float
    total_equity: float
    market_cap: float
    profit_ltm: float
    observed_multiple: Optional[float]

    def as_dict(self) -> dict:
        return {
            "year": self.year,
            "tickers": self.tickers,
            "companies": self.companies,
            "payout": self.payout,
            "roe": self.roe,
            "sustainable_growth": self.growth,
            "total_dividends": round(self.total_dividends, 1),
            "total_profit": round(self.total_profit, 1),
            "total_equity": round(self.total_equity, 1),
            "market_cap": round(self.market_cap, 1),
            "profit_ltm": round(self.profit_ltm, 1),
            "observed_multiple": self.observed_multiple,
        }


def trustworthy_tickers(db: Session) -> list:
    """Компании, за которые можно ручаться: проверены и без дефектов аудита.

    Два условия обязательны оба. Пометка аналитика без аудита пропускает
    опечатки, аудит без пометки — пропускает компании, у которых просто
    нечего проверять: пустые поля дефектов не дают.
    """
    verified = {
        row[0]
        for row in db.execute(text(
            "select c.ticker from financial_reports r "
            "join companies c on c.id = r.company_id "
            "where r.period_type = 'ANNUAL' group by 1 "
            "having sum(case when r.verified_by_analyst then 1 else 0 end) = count(*)"
        ))
    }
    clean = {a.ticker for a in collect(set()) if a.clean}
    return sorted(verified & clean)


def snapshot(db: Session, year: int = DEFAULT_YEAR) -> MarketSnapshot:
    """Выплата, отдача, устойчивый рост и фактический P/E рынка."""
    tickers = trustworthy_tickers(db)

    rows = db.execute(text(
        "select m.ltm_dividends_per_share, m.shares_used, m.ltm_net_income, m.equity "
        "from multipliers m join companies c on c.id = m.company_id "
        "where m.type = 'report_based' and extract(year from m.date) = :y "
        "and c.ticker = any(:t)"
    ), {"y": year, "t": tickers}).fetchall()

    pairs, profit_total, equity_total = [], 0.0, 0.0
    for dps, shares, profit, equity in rows:
        if profit is None:
            continue
        dividends = 0.0
        if dps is not None and shares is not None:
            dividends = float(dps) * float(shares) / 1_000_000
        pairs.append((dividends, float(profit)))
        if equity is not None:
            profit_total += float(profit)
            equity_total += float(equity)

    observed = observed_payout(pairs)
    roe = round(profit_total / equity_total * 100.0, 2) if equity_total > 0 else None

    # Фактический множитель — по последнему срезу цен, а не по срезу за год:
    # сравнивать надо с тем, что рынок думает сейчас.
    current = db.execute(text(
        "select distinct on (m.company_id) m.market_cap, m.ltm_net_income "
        "from multipliers m join companies c on c.id = m.company_id "
        "where m.type = 'current' and c.ticker = any(:t) "
        "order by m.company_id, m.date desc"
    ), {"t": tickers}).fetchall()

    cap = sum(float(c) for c, p in current if c and p)
    profit_ltm = sum(float(p) for c, p in current if c and p)
    observed_multiple = round(cap / profit_ltm, 2) if profit_ltm > 0 else None

    return MarketSnapshot(
        year=year,
        tickers=tickers,
        companies=observed.companies,
        payout=observed.payout,
        roe=roe,
        growth=sustainable_growth(roe, observed.payout),
        total_dividends=observed.total_dividends,
        total_profit=observed.total_profit,
        total_equity=equity_total,
        market_cap=cap,
        profit_ltm=profit_ltm,
        observed_multiple=observed_multiple,
    )
