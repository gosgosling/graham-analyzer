from fastapi import APIRouter
from fastapi import HTTPException
from app.schemas import Security, CompanyResult, Multipliers, AnalysisItem, AnalysisResponse
from app.services.graham_analyser import classify_company
from app.data.mock_data import MOCK_COMPANIES, MOCK_MULTIPLIERS
from typing import LiteralString, Optional
from app.utils.moex_client import get_moex_securities

router = APIRouter(prefix="/securities", tags=["securities"])

@router.get("/", response_model=list[Security])
def get_securities():

    securities = get_moex_securities()

    
    
    return securities

def _get_multipliers_by_company_id(company_id: int) -> dict:
    """Вспомогательная функция для получения мультипликаторов"""
    multiplier = next((m for m in MOCK_MULTIPLIERS if m['company_id'] == company_id), None)
    if multiplier is None:
        raise HTTPException(status_code=404, detail='Multipliers not found')
    return multiplier

@router.get('/analysis', response_model=AnalysisResponse)
def get_analysis_companies():
    undervalued_companies = []
    stable_companies = []
    overvalued_companies = []
    securities = get_securities()
    for security in securities:
        multipliers = _get_multipliers_by_company_id(security['id'])
        classified_category = classify_company(multipliers) 
        if classified_category['classify'] == "undervalued": undervalued_companies.append({'security': security, 'multipliers': multipliers, 'category': classified_category['classify']})
        elif classified_category['classify'] == "stable": stable_companies.append({'security': security, 'multipliers': multipliers, 'category': classified_category['classify']})
        else:  overvalued_companies.append({'security': security, 'multipliers': multipliers, 'category': classified_category['classify']})
    return {"undervalued": undervalued_companies, "stable": stable_companies, "overvalued": overvalued_companies}


@router.get('/{company_id}', response_model=Security)
def get_company(company_id: int):
    company = next((security for security in get_securities() if security['id'] == company_id), None)
    if company is None:
        raise HTTPException(status_code=404, detail='Company not found')
    return company

@router.get('/{company_id}/multipliers', response_model=Multipliers)
def get_company_multipliers(company_id: int):
    multipliers = MOCK_MULTIPLIERS
    multipliers = next((multiplier for multiplier in multipliers if multiplier['company_id'] == company_id), None)
    if multipliers is None:
        raise HTTPException(status_code=404, detail='Multipliers not found')
    return multipliers


@router.get('/{company_id}/result', response_model=CompanyResult)
def get_company_result(company_id: int):
    company = next((c for c in MOCK_COMPANIES if c['id'] == company_id), None)
    if company is None:
        raise HTTPException(status_code=404, detail='Company not found')
    multipliers = _get_multipliers_by_company_id(company_id)
    category = classify_company(multipliers)
    result = {
        "company_id": company_id,
        "company_name": company['name'],
        "category": category['classify'],
        "multipliers": multipliers,
        "analysis": {
            "pe_ratio_status": category['pe_ratio_status'],
            "pb_ratio_status": category['pb_ratio_status'],
            "debt_status": category['debt_status'],
            "liquidity_status": category['liquidity_status'],
            "profitability_status": category['profitability_status']
            } ,
        "recommendation":  "Хз",
        "date": "2025-12-10"
    }
    return result
