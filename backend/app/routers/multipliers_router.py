"""
Роутер для работы с мультипликаторами.

Эндпоинты:
    GET  /companies/{company_id}/multipliers/current
        — Актуальные мультипликаторы (вычисляется на лету по LTM + текущая цена)

    POST /companies/{company_id}/multipliers/refresh
        — Обновить текущую цену из T-Invest API и пересчитать мультипликаторы

    GET  /companies/{company_id}/multipliers/history
        — История мультипликаторов (из кэша, для графиков)

    GET  /reports/{report_id}/multipliers
        — Мультипликаторы привязанные к конкретному отчёту
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.multiplier import Multiplier
from app.schemas import (
    MultiplierResponse,
    CurrentMultipliersResponse,
    PriceUpdateResponse,
)
from app.services.analysis import multiplier_service
from app.services.market import tinvest_price_service

router = APIRouter(tags=["multipliers"])


# ---------------------------------------------------------------------------
# Актуальные мультипликаторы (вычисляются на лету)
# ---------------------------------------------------------------------------

@router.get(
    "/companies/{company_id}/multipliers/current",
    response_model=CurrentMultipliersResponse,
    summary="Актуальные мультипликаторы компании",
    description=(
        "Рассчитывает мультипликаторы на лету: "
        "P&L по LTM (последние 12 месяцев), балансовые данные из свежайшего отчёта, "
        "цена — текущая (из поля company.current_price или переданная в price)."
    ),
)
def get_current_multipliers(
    company_id: int,
    price: Optional[float] = Query(None, description="Переопределить текущую цену акции"),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания с ID {company_id} не найдена",
        )

    result = multiplier_service.calculate_current_multipliers(
        db=db,
        company_id=company_id,
        price_override=price,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Недостаточно данных для расчёта мультипликаторов. "
                "Проверьте наличие финансовых отчётов и текущей цены акции."
            ),
        )

    return CurrentMultipliersResponse(**result)


# ---------------------------------------------------------------------------
# Обновить цену и пересчитать мультипликаторы
# ---------------------------------------------------------------------------

@router.post(
    "/companies/{company_id}/multipliers/refresh",
    response_model=PriceUpdateResponse,
    summary="Обновить цену из T-Invest API и пересчитать мультипликаторы",
)
def refresh_multipliers(
    company_id: int,
    save_to_cache: bool = Query(True, description="Сохранить рассчитанные мультипликаторы в кэш"),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания с ID {company_id} не найдена",
        )

    price = tinvest_price_service.update_company_price(db=db, company=company)

    if save_to_cache and price is not None:
        mults = multiplier_service.calculate_current_multipliers(
            db=db,
            company_id=company_id,
        )
        if mults:
            multiplier_service.save_current_multiplier(db=db, company_id=company_id, mults=mults)

    return PriceUpdateResponse(
        company_id=company_id,
        ticker=company.ticker,
        figi=company.figi,
        price=price,
        updated_at=company.price_updated_at,
        success=price is not None,
    )


# ---------------------------------------------------------------------------
# История мультипликаторов (из кэша)
# ---------------------------------------------------------------------------

@router.get(
    "/companies/{company_id}/multipliers/history",
    response_model=List[MultiplierResponse],
    summary="История мультипликаторов компании",
    description="Возвращает кэшированные мультипликаторы для построения графиков.",
)
def get_multipliers_history(
    company_id: int,
    type: Optional[str] = Query(
        None,
        description="Тип записи: report_based | current | daily. Если не указан — все типы.",
    ),
    limit: int = Query(365, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Компания с ID {company_id} не найдена",
        )

    history = multiplier_service.get_multipliers_history(
        db=db,
        company_id=company_id,
        mult_type=type,
        limit=limit,
    )
    return history


# ---------------------------------------------------------------------------
# Мультипликаторы по конкретному отчёту
# ---------------------------------------------------------------------------

@router.get(
    "/reports/{report_id}/multipliers",
    response_model=MultiplierResponse,
    summary="Мультипликаторы на дату отчёта",
    description=(
        "Возвращает кэшированные мультипликаторы типа report_based для отчёта. "
        "Если кэш не найден — рассчитывает на лету и сохраняет."
    ),
)
def get_report_multipliers(
    report_id: int,
    db: Session = Depends(get_db),
):
    report = db.query(FinancialReport).filter(FinancialReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчёт с ID {report_id} не найден",
        )

    # Ищем кэш
    cached: Optional[Multiplier] = (
        db.query(Multiplier)
        .filter(
            Multiplier.report_id == report_id,
            Multiplier.type == "report_based",
        )
        .first()
    )

    if cached:
        return cached

    # Не нашли — вычисляем и сохраняем
    saved = multiplier_service.save_report_based_multiplier(db=db, report=report)
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Недостаточно данных в отчёте для расчёта мультипликаторов "
                "(нужны цена акции и количество акций)."
            ),
        )
    return saved


# ---------------------------------------------------------------------------
# Массовое обновление цен всех компаний
# ---------------------------------------------------------------------------

@router.post(
    "/multipliers/refresh-all-prices",
    summary="Обновить цены всех компаний из T-Invest API",
    description="Батч-обновление текущих цен для всех компаний в БД. Один вызов к API.",
)
def refresh_all_prices(
    save_to_cache: bool = Query(False, description="Сохранить пересчитанные мультипликаторы в кэш"),
    db: Session = Depends(get_db),
):
    prices = tinvest_price_service.update_all_company_prices(db=db)

    if save_to_cache:
        updated_count = 0
        companies = db.query(Company).filter(Company.current_price.isnot(None)).all()
        for company in companies:
            mults = multiplier_service.calculate_current_multipliers(
                db=db, company_id=company.id
            )
            if mults:
                multiplier_service.save_current_multiplier(
                    db=db, company_id=company.id, mults=mults
                )
                updated_count += 1

        return {
            "prices_updated": sum(1 for v in prices.values() if v is not None),
            "total_companies": len(prices),
            "multipliers_cached": updated_count,
        }

    return {
        "prices_updated": sum(1 for v in prices.values() if v is not None),
        "total_companies": len(prices),
        "prices": prices,
    }
