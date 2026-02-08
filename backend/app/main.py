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
