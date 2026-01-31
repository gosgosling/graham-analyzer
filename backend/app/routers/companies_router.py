from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.schemas import Company
from app.utils.tinkoff_client import get_tinkoff_companies
from typing import List
from app.schemas import Company
from app.database import get_db
from app.services.company_service import get_all_companies
from app.services.sync_service import sync_companies_from_tinkoff
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
        return {
            "status": "success",
            "message": "Синхронизация завершена",
            "statistics": stats
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при синхронизации: {str(e)}"
        )


