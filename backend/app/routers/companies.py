from fastapi import APIRouter
from fastapi import HTTPException
from app.schemas import Company, Multipliers, AnalysisItem, AnalysisResponse


router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("/", response_model=list[Company])
def get_companies():
    companies = [
        {
            'id': 1,
            'name': 'Lukoil',
            'ticker': 'LKOH',
            'sector': 'Oil and Gas',
            'industry': 'Oil and Gas Exploration and Production'
        },
        {
            'id': 2,
            'name': 'Rosneft',
            'ticker': 'ROSN',
            'sector': 'Oil and Gas',
            'industry': 'Oil and Gas Exploration and Production'
        },
        {
            'id': 3,
            'name': 'Gazprom',
            'ticker': 'GAZP',
            'sector': 'Oil and Gas',
            'industry': 'Oil and Gas Exploration and Production'
        },
        {
            'id': 4,
            'name': 'Sberbank',
            'ticker': 'SBER',
            'sector': 'Banking',
            'industry': 'Banking'
        },
        {
            'id': 5,
            'name': 'Alfa-Bank',
            'ticker': 'ALFA',
            'sector': 'Banking',
            'industry': 'Banking'
        },
    ]
    return companies

@router.get('/analysis', response_model=AnalysisResponse)
def get_analysis_companies():
    undervalued_companies = []
    stable_companies = []
    overvalued_companies = []
    companies = get_companies()
    for company in companies:
        multipliers = get_company_multipliers(company['id'])
        classified_category = classify_company(multipliers) 
        if classified_category == "undervalued": undervalued_companies.append({'company': company, 'multipliers': multipliers, 'category': classified_category})
        elif classified_category == "stable": stable_companies.append({'company': company, 'multipliers': multipliers, 'category': classified_category})
        else:  overvalued_companies.append({'company': company, 'multipliers': multipliers, 'category': classified_category})
    return {"undervalued": undervalued_companies, "stable": stable_companies, "overvalued": overvalued_companies}


@router.get('/{company_id}', response_model=Company)
def get_company(company_id: int):
    company = next((company for company in get_companies() if company['id'] == company_id), None)
    if company is None:
        raise HTTPException(status_code=404, detail='Company not found')
    return company

@router.get('/{company_id}/multipliers', response_model=Multipliers)
def get_company_multipliers(company_id: int):
    multipliers = [
        {
            "company_id": 1,
            "pe_ratio": 12.5,
            "pb_ratio": 1.2,
            "debt_to_equity": 0.3,
            "current_ratio": 2.5,
            "roe": 18.5,
            "dividend_yield": 4.2,
            "date": "2025-01-01"
        }, 
        {
            "company_id": 2,
            "pe_ratio": 15.2,
            "pb_ratio": 1.5,
            "debt_to_equity": 0.4,
            "current_ratio": 2.8,
            "roe": 19.2,
            "dividend_yield": 3.8,
            "date": "2025-01-02"
        },
        {
            "company_id": 3,
            "pe_ratio": 17.8,
            "pb_ratio": 2.1,
            "debt_to_equity": 0.2,
            "current_ratio": 2.7,
            "roe": 9.8,
            "dividend_yield": 3.5,
            "date": "2025-01-03"
        },
        {
            "company_id": 4,
            "pe_ratio": 14.5,
            "pb_ratio": 1.4,
            "debt_to_equity": 0.5,
            "current_ratio": 2.6,
            "roe": 16.5,
            "dividend_yield": 3.9,
            "date": "2025-01-04"
        },
        {
            "company_id": 5,
            "pe_ratio": 16.3,
            "pb_ratio": 1.6,
            "debt_to_equity": 0.6,
            "current_ratio": 2.9,
            "roe": 17.1,
            "dividend_yield": 4.1,
            "date": "2025-01-05"
        },
    ]
    multipliers = next((multiplier for multiplier in multipliers if multiplier['company_id'] == company_id), None)
    if multipliers is None:
        raise HTTPException(status_code=404, detail='Multipliers not found')
    return multipliers

def classify_company(multipliers):
    pe = multipliers['pe_ratio']
    pb = multipliers['pb_ratio']
    debt_to_equity = multipliers['debt_to_equity']
    current_ratio = multipliers['current_ratio']
    roe = multipliers['roe']
    dividend_yield = multipliers['dividend_yield']
    is_undervalued = (pe < 15 and pb < 1.5 and debt_to_equity <= 0.5 and current_ratio > 2.0 and roe > 15 and dividend_yield > 3)
    is_stable = ( 15 <= pe <= 25 and 1.5 <= pb <= 3.0 and debt_to_equity < 1 and current_ratio > 1.5 and roe > 10 and dividend_yield > 3)  
    if is_undervalued: return "undervalued"
    if is_stable: return "stable"
    return "overvalued"
    #if pe < 15 and pb < 1.5 and debt_to_equity < 0.5 and current_ratio > 2.0 and roe > 15 and dividend_yield > 3:
     #   return 'undervalued'
    #elif  pe < 25 and pb < 3 and debt_to_equity < 1 and current_ratio > 1.5 and roe > 10 and dividend_yield > 3:
     #   return 'stable'
    #else:
     #   return 'overvalued'