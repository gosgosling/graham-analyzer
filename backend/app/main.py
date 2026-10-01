from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from app.routers import valuation_router, screen_router, companies_router, securities_router, reports_router, dividends_router, prices_router
from app.routers import multipliers_router, market_router, bonds_router, admin_router
from app.routers import mass_parse_router, disclosure_router, holdings_router, auth_router
from app.scheduler import start_scheduler, stop_scheduler
from app.services.mass_parse.worker import recover_orphaned_running_jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Запускает планировщик при старте и останавливает при завершении."""
    recover_orphaned_running_jobs()
    start_scheduler()
    yield
    stop_scheduler()


from app.config import allowed_origins, settings  # noqa: E402

# Документация API в бою закрыта: она — карта всех эндпоинтов, включая
# служебные. Локально (DEBUG) открыта.
app = FastAPI(
    title='Graham Analyzer',
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# Порядок важен: прослойка, добавленная последней, — внешняя. CORS снаружи
# проверки доступа, иначе отказ 401/403 уйдёт без CORS-заголовков и браузер
# покажет его как сетевую ошибку.
from app.utils.admin_guard import AdminGuardMiddleware, SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(AdminGuardMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
)

app.include_router(auth_router.router)
app.include_router(securities_router.router)
app.include_router(companies_router.router)
app.include_router(reports_router.router)
app.include_router(dividends_router.router)
app.include_router(multipliers_router.router)
app.include_router(market_router.router)
app.include_router(bonds_router.router)
app.include_router(admin_router.router)
app.include_router(mass_parse_router.router)
app.include_router(disclosure_router.router)
app.include_router(holdings_router.router)
app.include_router(valuation_router.router)
app.include_router(screen_router.router)
app.include_router(prices_router.router)


@app.get('/health')
def health_check():
    return {'status': 'ok'}
