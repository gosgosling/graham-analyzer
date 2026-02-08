from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict

from app.database import get_db
from app.schemas import DividendContinuityResult
from app.services.dividend_service import (
    calculate_dividend_continuity,
    get_dividend_history,
    update_dividend_start_year
)

router = APIRouter(prefix="/dividends", tags=["dividends"])


@router.get("/company/{company_id}/analysis", response_model=DividendContinuityResult)
def analyze_dividend_continuity(
    company_id: int,
    min_years: int = 20,
    db: Session = Depends(get_db)
):
    """Анализирует непрерывность выплаты дивидендов компании по методу Грэма."""
    try:
        result = calculate_dividend_continuity(db, company_id, min_years)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")


@router.get("/company/{company_id}/history")
def get_company_dividend_history(company_id: int, db: Session = Depends(get_db)) -> List[Dict]:
    """Получает историю выплаты дивидендов компании."""
    try:
        return get_dividend_history(db, company_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {str(e)}")
