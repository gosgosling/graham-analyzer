"""Логотипы компаний с нашего сервера (см. `services/companies/logo_cache.py`)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.services.companies import logo_cache

router = APIRouter(prefix="/logos", tags=["logos"])


@router.get("/{ticker}.png")
def company_logo(ticker: str, db: Session = Depends(get_db)):
    path = logo_cache.cached_path(ticker)
    if path is None:
        company = db.query(Company).filter(Company.ticker == ticker.upper()).first()
        path = logo_cache.ensure(company) if company is not None else None
    if path is None:
        # 404 без тела: фронтенд в этом случае пробует CDN, а за ним — пустое место.
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
