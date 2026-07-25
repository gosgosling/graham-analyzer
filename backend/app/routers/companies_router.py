import os

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.schemas import Company, CompanyDescriptionUpdate, SectorProfileOption
from typing import List, Optional
from app.database import get_db
from app.services.analysis.sector_profiles import available_profiles
from app.services.companies.company_service import (
    get_all_companies,
    get_company_by_id,
    set_business_description_manual,
    set_preferred_share_flag,
    set_sector_profile_key,
)
from app.services.companies.sync_service import sync_companies_from_tinkoff
from app.models.company import Company as CompanyModel


class PreferredShareUpdate(BaseModel):
    """Тело PATCH /companies/{id}/preferred-share: новое значение флажка."""
    is_preferred_share: bool


class SectorProfileUpdate(BaseModel):
    """Тело PATCH /companies/{id}/sector-profile; null возвращает автоопределение."""
    sector_profile_key: Optional[str] = None

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

# Объявлено до "/{company_id}": иначе FastAPI попытается разобрать
# "sector-profiles" как целочисленный ID и вернёт 422.
@router.get("/sector-profiles", response_model=List[SectorProfileOption])
def list_sector_profiles():
    """
    Доступные отраслевые профили порогов — для выбора аналитиком в карточке
    компании, когда сектор из T-Invest слишком крупный («consumer» — это и
    продуктовая сеть, и магазин электроники).
    """
    return list(available_profiles())


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


@router.patch("/{company_id}/preferred-share", response_model=Company)
def update_preferred_share_flag(
    company_id: int,
    payload: PreferredShareUpdate,
    db: Session = Depends(get_db),
):
    """
    Ручное переключение флажка «инструмент — привилегированные акции».
    Применяется в карточке компании; имеет приоритет над авто-детектом
    на следующей синхронизации с T-Invest.
    """
    company = set_preferred_share_flag(db, company_id, payload.is_preferred_share)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.patch("/{company_id}/sector-profile", response_model=Company)
def update_sector_profile(
    company_id: int,
    payload: SectorProfileUpdate,
    db: Session = Depends(get_db),
):
    """
    Закрепляет за компанией профиль порогов. Пустое значение возвращает
    автоопределение по сектору. Выбор сохраняется при синхронизации с T-Invest.
    """
    try:
        company = set_sector_profile_key(db, company_id, payload.sector_profile_key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.patch("/{company_id}/description", response_model=Company)
def update_company_description(
    company_id: int,
    payload: CompanyDescriptionUpdate,
    db: Session = Depends(get_db),
):
    """
    Ручное описание деятельности компании аналитиком.
    Имеет приоритет над автоматическим извлечением из отчётов (LLM).
    """
    company = set_business_description_manual(
        db, company_id, payload.business_description
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company

