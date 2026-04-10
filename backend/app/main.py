from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from app.routers import companies_router, securities_router, reports_router, dividends_router
from app.routers import multipliers_router, market_router, bonds_router
from app.schemas import AnalysisResponse, Security, Multipliers
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запускает планировщик при старте и останавливает при завершении."""
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title='Graham Analyzer', lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(securities_router.router)
app.include_router(companies_router.router)
app.include_router(reports_router.router)
app.include_router(dividends_router.router)
app.include_router(multipliers_router.router)
app.include_router(market_router.router)
app.include_router(bonds_router.router)


@app.get('/health')
def health_check():
    return {'status': 'ok'}
