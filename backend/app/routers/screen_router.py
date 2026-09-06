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
from app.services.analysis import market_snapshot, screen, screen_axes
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

    results = [screen.load(db, company, standard) for company in companies]
    results = [r for r in results if r.verdicts]

    columns: list = []
    seen: set = set()
    for result in results:
        for verdict in result.verdicts:
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

    rows = []
    for result, company in zip(results, companies):
        by_metric = {v.metric: v for v in result.verdicts}
        rows.append({
            "id": company.id,
            "ticker": result.ticker,
            "name": company.name,
            "profile": result.profile.key,
            "profile_label": result.profile.label,
            "passed": result.passed,
            "checked": len(result.checkable),
            "clears": result.clears,
            "complete": result.complete,
            "cells": [
                (by_metric[c["metric"]].as_dict() if c["metric"] in by_metric else None)
                for c in columns
            ],
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
