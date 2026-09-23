"""Экран Грэма: паспорт компании и сводная таблица по рынку.

Два представления одного расчёта. Паспорт показывает одну компанию по всем
осям сразу — с рядом по годам, обоими порогами и источником каждого. Сводная
таблица показывает весь рынок по одному своду — и отвечает на вопрос, который
в паспорте не виден: провалилась компания по своей вине или по той же причине,
что и все остальные.

Оба свода отдаются вместе. Компания редко интересна только одним: «не проходит
у защитного инвестора, проходит у активного» — это и есть ответ, а не
полуответ, и заставлять фронт ходить дважды ради него незачем.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.market_assumption import MarketAssumption
from app.services.analysis import market_snapshot, screen, screen_axes
from app.services.analysis.company_valuation import DEFAULT_WINDOW, assess
from app.services.analysis.sector_profiles import profile_to_dict

router = APIRouter(prefix="/screen", tags=["screen"])


def _company(db: Session, company_id: int) -> Company:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return company


@router.get("/standards")
def standards() -> dict:
    """Своды критериев для переключателя."""
    return {
        "standards": [
            {"key": key, "label": screen.STANDARD_LABELS[key]}
            for key in screen.STANDARDS
        ],
        "default": screen.STANDARDS[0],
    }


@router.get("/company/{company_id}")
def company_passport(
    company_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Паспорт: все оси с рядами плюс приговор по обоим сводам."""
    company = _company(db, company_id)
    axes = screen_axes.load(db, company)
    profile = screen.profile_for(db, company)
    screens = {
        name: screen.apply(axes, profile, name, ticker=str(company.ticker))
        for name in screen.STANDARDS
    }
    return {
        "company": {
            "id": company.id,
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
        },
        "profile": profile_to_dict(profile),
        "order": list(screen_axes.AXIS_ORDER),
        "axes": screen_axes.as_dict(axes),
        "screens": {name: result.as_dict() for name, result in screens.items()},
    }


@router.get("/market")
def market_screen(
    standard: str = Query("defensive", description="свод критериев"),
    all_companies: bool = Query(
        False, alias="all",
        description="все компании базы, а не только проверенные",
    ),
    db: Session = Depends(get_db),
) -> dict:
    """Сводная таблица: один свод, все компании, по столбцу на критерий.

    По умолчанию берутся только проверенные компании. Считать по всей базе
    можно, но толку в этом мало: строка, собранная из непроверенных данных,
    выглядит точно так же, как настоящая, и отличить их в таблице нельзя.
    """
    if standard not in screen.STANDARDS:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестный свод: {standard}. Есть {', '.join(screen.STANDARDS)}",
        )

    if all_companies:
        companies = db.query(Company).order_by(Company.ticker).all()
    else:
        tickers = market_snapshot.trustworthy_tickers(db)
        companies = [
            company for company in (
                db.query(Company).filter(Company.ticker == ticker).first()
                for ticker in tickers
            ) if company is not None
        ]

    # Пары «результат — компания» держатся вместе с самого начала.
    #
    # Раньше результаты отсеивались отдельным списком, а ниже шёл
    # `zip(results, companies)`. Пока отсеивать было нечего, это работало; но
    # стоило одной компании остаться без вердиктов — и всё, что ниже неё по
    # списку, получало чужие данные, а хвост молча пропадал. Ошибка тихая:
    # таблица остаётся полной на вид, просто в строке «Татнефть» стоят числа
    # соседа.
    pairs = [
        (result, company)
        for company, result in (
            (company, screen.load(db, company, standard)) for company in companies
        )
        if result.verdicts
    ]
    results = [result for result, _ in pairs]

    # Банковские критерии своих колонок не получают: они есть у трёх компаний
    # из тридцати шести, и ради них таблица вырастала на четверть, а у всех
    # прочих эти столбцы стояли пустыми. Вместо этого они занимают те ячейки,
    # которые банк оставляет пустыми сам, — ликвидность и три по свободному
    # потоку. Ровно четыре пустые клетки и ровно четыре показателя.
    # Порядок подстановки — по смыслу, а не по случаю. Ликвидность и
    # достаточность капитала отвечают на один вопрос: хватит ли запаса.
    # Безубыточность по потоку и стоимость риска — на другой: ровно ли идёт
    # дело. Первые две пары ложатся точно, оставшиеся две занимают что
    # осталось, и только имя в клетке говорит, что там на самом деле.
    LENDER_ORDER = ("capital_core", "cost_of_risk_average",
                    "npl_ratio", "cost_to_income_average")
    lender_metrics = set(LENDER_ORDER)

    columns: list = []
    seen: set = set()
    for result in results:
        for verdict in result.verdicts:
            if verdict.metric in lender_metrics:
                continue
            if verdict.metric not in seen:
                seen.add(verdict.metric)
                columns.append({
                    "metric": verdict.metric,
                    "label": verdict.metric_label,
                    "axis": verdict.axis,
                    "axis_label": verdict.label,
                    "book": verdict.book,
                    "book_text": verdict.rule.text(verdict.book),
                    "source": verdict.rule.source,
                    "ours": verdict.rule.ours,
                })

    # Сигнал о цене рядом со сводом. Свод отвечает на вопрос «хороша ли
    # компания», сигнал — «хороша ли цена», и это разные вопросы: в паспорте
    # они стоят рядом, а в таблице до сих пор был только первый.
    #
    # Приговор свода передаётся готовым: он уже посчитан выше, и считать его
    # вторым заходом внутри оценки значило бы удваивать самую дорогую часть.
    assumption = (
        db.query(MarketAssumption).order_by(MarketAssumption.year.desc()).first()
    )

    rows = []
    for result, company in pairs:
        by_metric = {v.metric: v for v in result.verdicts}
        # Подстановка: пустые клетки банка заполняются его собственными
        # показателями. Имя показателя едет вместе со значением — без него
        # цифра в чужой колонке прочиталась бы как ликвидность.
        spare = [
            by_metric[m].as_dict() for m in LENDER_ORDER
            if m in by_metric and by_metric[m].status != screen.NOT_APPLICABLE
        ]
        cells = []
        for column in columns:
            cell = by_metric.get(column["metric"])
            payload = cell.as_dict() if cell is not None else None
            if spare and payload is not None and payload["status"] == screen.NOT_APPLICABLE:
                payload = spare.pop(0)
            cells.append(payload)

        # Оценка может отказать — тогда сигнала просто нет, и строка живёт
        # дальше одним сводом. Падать из-за одной компании таблица не должна.
        safety = None
        if assumption is not None:
            try:
                valuation = assess(db, company, assumption, DEFAULT_WINDOW,
                                   screen_clears=result.clears)
                if valuation.get("available"):
                    payload_safety = valuation.get("safety")
                    if payload_safety and payload_safety["signal"] != "no_signal":
                        safety = payload_safety
            except Exception:
                safety = None

        rows.append({
            "id": company.id,
            "ticker": result.ticker,
            "name": company.name,
            # Логотип для опознания строки с одного взгляда: в таблице на
            # тридцать компаний тикер читается медленнее, чем знакомый кружок.
            "logo_url": str(company.brand_logo_url) if company.brand_logo_url else None,
            "profile": result.profile.key,
            "profile_label": result.profile.label,
            "passed": result.passed,
            "checked": len(result.checkable),
            "clears": result.clears,
            "complete": result.complete,
            "safety": safety,
            "cells": cells,
        })

    fails: dict = {}
    for result in results:
        for verdict in result.failed:
            fails[verdict.metric] = fails.get(verdict.metric, 0) + 1

    return {
        "standard": standard,
        "standard_label": screen.STANDARD_LABELS[standard],
        "columns": columns,
        "rows": sorted(rows, key=lambda r: (-r["passed"], r["ticker"])),
        "summary": {
            "total": len(rows),
            "cleared": sum(1 for r in rows if r["clears"]),
            "fails": dict(sorted(fails.items(), key=lambda pair: -pair[1])),
        },
    }
