"""Доступ к БД приложения для CLI-утилиты.

Тонкий слой поверх backend моделей. config.py должен быть импортирован
первым (он настраивает sys.path).
"""
from __future__ import annotations

import config  # noqa: F401  # настраивает sys.path и загружает env

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings as backend_settings
from app.models.company import Company

_engine = create_engine(backend_settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def open_session() -> Session:
    return SessionLocal()


def get_company_by_ticker(db: Session, ticker: str):
    return db.query(Company).filter(Company.ticker.ilike(ticker)).first()


def list_known_tickers(db: Session) -> list[str]:
    rows = db.query(Company.ticker).order_by(Company.ticker).all()
    return [r[0] for r in rows]


__all__ = (
    "Company",
    "SessionLocal",
    "get_company_by_ticker",
    "list_known_tickers",
    "open_session",
)
