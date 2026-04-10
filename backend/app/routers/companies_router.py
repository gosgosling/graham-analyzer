import os

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.schemas import Company
from typing import List
from app.database import get_db
from app.services.companies.company_service import get_all_companies, get_company_by_id
from app.services.companies.sync_service import sync_companies_from_tinkoff
from app.models.company import Company as CompanyModel

router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("/", response_model=list[Company])
def get_companies(skip: int = 0, limit: int = 200, db: Session = Depends(get_db)):
    """
    Получает список компаний из базы данных.
    
    Args:
        skip: Количество записей для пропуска (пагинация)
        limit: Максимальное количество записей
        db: Сессия БД (автоматически через Depends)
        
    Returns:
        Список компаний из БД
    """
    companies = get_all_companies(db, skip=skip, limit=limit)
    return companies

@router.get("/sync/status")
def companies_sync_status(db: Session = Depends(get_db)):
    """
    Диагностика: сколько компаний в БД, сколько с логотипом/цветом бренда, настроен ли токен.
    """
    token = (os.getenv("TINKOFF_TOKEN") or "").strip()
    bad = {"", "token", "your_token_here", "tocken"}
    token_ok = bool(token) and token.lower() not in bad

    total = db.query(CompanyModel).count()
    with_logo = (
        db.query(CompanyModel)
        .filter(CompanyModel.brand_logo_url.isnot(None))
        .filter(CompanyModel.brand_logo_url != "")
        .count()
    )
    with_color = (
        db.query(CompanyModel)
        .filter(CompanyModel.brand_color.isnot(None))
        .filter(CompanyModel.brand_color != "")
        .count()
    )

    return {
        "token_configured": token_ok,
        "companies_total": total,
        "companies_with_brand_logo": with_logo,
        "companies_with_brand_color": with_color,
    }


@router.post("/sync")
def sync_companies(db: Session = Depends(get_db)):
    """
    Синхронизирует компании из Tinkoff API в базу данных.
    
    Этот endpoint:
    1. Получает данные из Tinkoff API
    2. Сохраняет их в БД (создает новые или обновляет существующие)
    
    Returns:
        Статистика синхронизации
    """
    try:
        stats = sync_companies_from_tinkoff(db)
        if stats.get("total", 0) == 0:
            return {
                "status": "warning",
                "message": (
                    "Список из T-Invest пуст. Проверьте TINKOFF_TOKEN в .env на сервере "
                    "и доступность API (см. GET /companies/sync/status)."
                ),
                "statistics": stats,
            }
        return {
            "status": "success",
            "message": "Синхронизация завершена. Логотипы и цвета подгружаются из API (ShareBy).",
            "statistics": stats,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при синхронизации: {str(e)}"
        )

@router.get("/{company_id}", response_model=Company)
def get_company(company_id: int, db: Session = Depends(get_db)):
    """
    Получает информацию о компании по её ID.
    
    Args:
        company_id: ID компании в базе данных
        db: Сессия БД
        
    Returns:
        Данные компании
        
    Raises:
        HTTPException: Если компания не найдена
    """
    company = get_company_by_id(db, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company

