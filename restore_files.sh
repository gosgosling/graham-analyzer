#!/bin/bash
# Скрипт восстановления всех потерянных файлов
echo "Восстановление файлов..."

# 1. Обновляем reports_router.py (добавляем endpoint /with-rub)
cat > backend/app/routers/reports_router.py << 'REPORTS_EOF'
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.schemas import FinancialReport, FinancialReportCreate
from app.services import report_service
from app.utils.currency_converter import get_report_with_rub_values

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/", response_model=FinancialReport, status_code=status.HTTP_201_CREATED)
def create_financial_report(
    report_data: FinancialReportCreate,
    db: Session = Depends(get_db)
):
    """Создать новый финансовый отчет."""
    try:
        return report_service.create_report(db=db, report_data=report_data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка при создании отчета: {str(e)}"
        )


@router.get("/", response_model=List[FinancialReport])
def get_all_reports(
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db)
):
    """Получить все финансовые отчеты (с пагинацией)."""
    return report_service.get_all_reports(db=db, skip=skip, limit=limit)


@router.get("/{report_id}", response_model=FinancialReport)
def get_report(report_id: int, db: Session = Depends(get_db)):
    """Получить финансовый отчет по ID."""
    report = report_service.get_report_by_id(db=db, report_id=report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return report


@router.get("/{report_id}/with-rub")
def get_report_with_rub(report_id: int, db: Session = Depends(get_db)):
    """Получить отчет с дополнительными полями в рублях."""
    report = report_service.get_report_by_id(db=db, report_id=report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return get_report_with_rub_values(report)


@router.get("/company/{company_id}", response_model=List[FinancialReport])
def get_company_reports(
    company_id: int,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Получить все отчеты для конкретной компании."""
    return report_service.get_reports_by_company(
        db=db,
        company_id=company_id,
        skip=skip,
        limit=limit
    )


@router.get("/company/{company_id}/latest", response_model=FinancialReport)
def get_latest_company_report(company_id: int, db: Session = Depends(get_db)):
    """Получить последний отчет для компании."""
    report = report_service.get_latest_report(db=db, company_id=company_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчеты для компании с ID {company_id} не найдены"
        )
    return report


@router.put("/{report_id}", response_model=FinancialReport)
def update_financial_report(
    report_id: int,
    report_data: FinancialReportCreate,
    db: Session = Depends(get_db)
):
    """Обновить существующий финансовый отчет."""
    updated_report = report_service.update_report(
        db=db,
        report_id=report_id,
        report_data=report_data
    )
    if not updated_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return updated_report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_financial_report(report_id: int, db: Session = Depends(get_db)):
    """Удалить финансовый отчет."""
    success = report_service.delete_report(db=db, report_id=report_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Отчет с ID {report_id} не найден"
        )
    return None
REPORTS_EOF

# 2. Обновляем main.py
cat > backend/app/main.py << 'MAIN_EOF'
from unicodedata import category
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Optional
from app.routers import companies_router, companies, reports_router, dividends_router
from app.schemas import AnalysisResponse, Security, Multipliers

app = FastAPI(title='Graham Analyzer')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(companies_router.router)
app.include_router(reports_router.router)
app.include_router(dividends_router.router)

@app.get('/health')
def health_check():
    return {'status': 'ok'}
MAIN_EOF

echo "Backend файлы восстановлены!"
