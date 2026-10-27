"""Таблица компаний: обычные рыночные и отчётные показатели одной строкой.

Скринер отвечает на вопрос Грэма, карточка — про одну компанию. Здесь — то,
с чего инвестор начинает знакомство с рынком: кто большой, кто зарабатывает,
у кого долг, — и всё это можно отсортировать. Как таблица акций на Investing,
только с прибылью и балансом за последние 12 месяцев из сверенной отчётности.

Откуда числа:
- отчётные (выручка и прибыль за 12 месяцев, активы, капитал, чистый долг,
  ROE) — последняя строка `multipliers` типа `current`: LTM по отчётам и
  баланс свежайшего из них;
- цена — `companies.current_price`, её каждые пять минут обновляет
  планировщик; вчерашнее закрытие — последняя дневная цена до сегодняшнего дня;
- рыночные (капитализация, P/E, P/B, дивидендная доходность) пересчитаны на
  текущую цену: в строке `multipliers` они по цене дня её записи, а отчётная
  часть между отчётами не меняется, так что пересчёт — одно отношение цен.

Компании без отчётов в таблице остаются — с ценой и капитализацией по числу
акций в выпуске, если оно известно: найти компанию в списке важнее, чем
увидеть у неё все колонки.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.company import Company


def _f(value) -> Optional[float]:
    return None if value is None else float(value)


def build(db: Session) -> dict:
    from app.services.analysis.market_snapshot import trustworthy_tickers

    latest = {
        row.company_id: row
        for row in db.execute(text(
            "select distinct on (company_id) company_id, date, price_used, market_cap, "
            "ltm_revenue, ltm_net_income, total_assets, equity, net_debt, "
            "pe_ratio, pb_ratio, dividend_yield, roe "
            "from multipliers where type = 'current' "
            "order by company_id, date desc"
        ))
    }
    previous = {
        row.company_id: row
        for row in db.execute(text(
            "select distinct on (company_id) company_id, date, price "
            "from stock_prices where date < :today "
            "order by company_id, date desc"
        ), {"today": date.today()})
    }
    last_close = {
        row.company_id: row
        for row in db.execute(text(
            "select distinct on (company_id) company_id, date, price "
            "from stock_prices order by company_id, date desc"
        ))
    }
    verified = set(trustworthy_tickers(db))

    rows = []
    for company in db.query(Company).order_by(Company.ticker):
        m = latest.get(company.id)
        close = last_close.get(company.id)
        price = _f(company.current_price) or (None if close is None else _f(close.price))
        prev = previous.get(company.id)
        prev_price = None if prev is None else _f(prev.price)

        used = None if m is None else _f(m.price_used)
        # Во сколько раз цена ушла с дня записи мультипликаторов.
        scale = price / used if price and used else None

        def market(value, inverse=False):
            value = _f(value)
            if value is None or scale is None:
                return value
            return value / scale if inverse else value * scale

        market_cap = market(m.market_cap) if m is not None else None
        by_issue = (price * float(company.issue_size) / 1_000_000
                    if price and company.issue_size else None)
        if market_cap is None:
            market_cap = by_issue
        # Непроверенный отчёт с ошибкой в числе акций (тысячи вместо штук)
        # давал Лензолоту и РКК «Энергия» капитализацию в триллионы и ставил их
        # первыми при сортировке. Если капитализация по отчёту расходится с
        # выпуском на бирже больше чем вдвое, а отчёт не сверен, берём выпуск и
        # от него пересчитываем P/E и P/B; дивидендную доходность (она на
        # акцию) не показываем. У сверенных расхождение законно: у
        # привилегированных выпуск — только своего типа, а капитализация — всей
        # компании.
        repaired = False
        verified_row = company.ticker in verified
        if (m is not None and not verified_row and by_issue and market_cap
                and not 0.5 <= market_cap / by_issue <= 2):
            market_cap, repaired = by_issue, True
        ni = None if m is None else _f(m.ltm_net_income)
        eq = None if m is None else _f(m.equity)

        rows.append({
            "id": company.id,
            "ticker": company.ticker,
            "name": company.name,
            "logo_url": company.brand_logo_url,
            "sector": company.sector,
            "verified": verified_row,
            "repaired": repaired,
            "has_reports": m is not None,
            "price": price,
            "change": (price / prev_price - 1) if price and prev_price else None,
            # Деньги — в млн ₽, как во всей базе.
            "market_cap": market_cap,
            "revenue": None if m is None else _f(m.ltm_revenue),
            "net_income": None if m is None else _f(m.ltm_net_income),
            "assets": None if m is None else _f(m.total_assets),
            "equity": None if m is None else _f(m.equity),
            "net_debt": None if m is None else _f(m.net_debt),
            "pe": (None if m is None else
                   (market_cap / ni if repaired and ni and ni > 0 else
                    None if repaired else market(m.pe_ratio))),
            "pb": (None if m is None else
                   (market_cap / eq if repaired and eq and eq > 0 else
                    None if repaired else market(m.pb_ratio))),
            "dividend_yield": (None if m is None or repaired
                               else market(m.dividend_yield, inverse=True)),
            "roe": None if m is None else _f(m.roe),
        })
    return {"asof": date.today().isoformat(), "rows": rows}
