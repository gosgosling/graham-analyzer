"""Прогрев кэша расчётов: тяжёлые ответы считаются в фоне, а не на запросе.

Планировщик раз в минуту сверяет версию данных. Если она сменилась — после
ежедневного обновления цен, загрузки отчёта, правки компании, — скринер,
сравнение, обзор рынка и оценки проверенных компаний пересчитываются здесь.
Посетитель получает готовый ответ из памяти.
"""
from __future__ import annotations

import logging
import threading
import time

from app.database import SessionLocal
from app.services import data_cache

logger = logging.getLogger(__name__)

_last_warmed: tuple | None = None
_running = threading.Lock()


def warm(force: bool = False) -> bool:
    """Пересчитать тяжёлые ответы, если данные изменились. True — считали."""
    global _last_warmed
    if not _running.acquire(blocking=False):
        return False  # прошлый прогрев ещё идёт
    try:
        version = data_cache.version()
        if not force and version == _last_warmed:
            return False
        from app.routers.compare_router import company_peers, compare_companies, compare_groups
        from app.routers.market_router import market_overview
        from app.routers.screen_router import market_screen
        from app.routers.valuation_router import DEFAULT_WINDOW, company_summary, market_multiple
        from app.services.analysis import screen
        from app.services.analysis.market_snapshot import DEFAULT_YEAR, trustworthy_tickers
        from app.models.company import Company

        started = time.perf_counter()
        db = SessionLocal()
        try:
            for standard in screen.STANDARDS:
                market_screen(standard=standard, all_companies=False, db=db)
            compare_groups(db=db)
            market_overview(db=db)
            market_multiple(year=None, data_year=DEFAULT_YEAR, db=db)
            tickers = trustworthy_tickers(db)
            for company in db.query(Company).filter(Company.ticker.in_(tickers)):
                try:
                    company_summary(company_id=company.id, window=DEFAULT_WINDOW, db=db)
                    company_peers(company_id=company.id, db=db)
                    # «Сравнить с отраслью» из карточки — компания и три соседки.
                    compare_companies(ids=None, with_id=company.id, all_peers=False, db=db)
                except Exception as e:  # noqa: BLE001 — одна компания не должна сорвать прогрев
                    logger.warning("Прогрев кэша: %s — %s", company.ticker, e)
        finally:
            db.close()
        _last_warmed = version
        logger.info("Прогрев кэша: %.1f с, записей %d", time.perf_counter() - started, data_cache.stats()["entries"])
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("Прогрев кэша не удался: %s", e)
        return False
    finally:
        _running.release()
