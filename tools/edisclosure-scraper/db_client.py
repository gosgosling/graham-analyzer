"""
Чтение списка компаний из PostgreSQL-базы основного приложения.
Если БД недоступна — возвращает список из mock_data.py.
"""

import logging
import sys
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class CompanyRecord(NamedTuple):
    ticker: str
    name: str


def get_companies_from_db() -> list[CompanyRecord]:
    """Возвращает список компаний из таблицы companies."""
    try:
        import psycopg2
    except ImportError:
        logger.warning("psycopg2 не установлен — используется mock-список.")
        return _get_mock_companies()

    from config import (
        POSTGRES_DB, POSTGRES_HOST, POSTGRES_PASSWORD,
        POSTGRES_PORT, POSTGRES_USER,
    )

    try:
        conn = psycopg2.connect(
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            connect_timeout=5,
        )
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ticker, name FROM companies ORDER BY ticker")
                rows = cur.fetchall()
        conn.close()

        if not rows:
            logger.warning("Таблица companies пуста — используется mock-список.")
            return _get_mock_companies()

        companies = [CompanyRecord(ticker=r[0], name=r[1]) for r in rows]
        logger.info("Загружено %d компаний из PostgreSQL.", len(companies))
        return companies

    except Exception as exc:
        logger.warning("Не удалось подключиться к PostgreSQL (%s) — используется mock-список.", exc)
        return _get_mock_companies()


def _get_mock_companies() -> list[CompanyRecord]:
    """Возвращает компании из mock_data.py основного бэкенда."""
    mock_path = Path(__file__).resolve().parent.parent / "backend" / "app" / "data" / "mock_data.py"

    if not mock_path.exists():
        logger.warning("mock_data.py не найден. Возвращается пустой список.")
        return []

    # Динамически импортируем без изменения sys.path навсегда
    import importlib.util
    spec = importlib.util.spec_from_file_location("mock_data", mock_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    companies = [
        CompanyRecord(ticker=c["ticker"], name=c["name"])
        for c in getattr(mod, "MOCK_COMPANIES", [])
    ]
    logger.info("Загружено %d компаний из mock_data.py.", len(companies))
    return companies
