from fastapi import APIRouter, HTTPException

from app.schemas import PostgresBackupResponse
from app.services.admin.backup_service import create_postgres_backup
from app.services.analysis import data_audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/backup/postgres", response_model=PostgresBackupResponse)
def backup_postgres():
    """
    Создаёт логический бэкап PostgreSQL (pg_dump -Fc) через scripts/pg_backup.sh.
    Файл сохраняется в backups/postgres/ или POSTGRES_BACKUP_DIR из окружения.
    """
    try:
        return create_postgres_backup()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/audit")
def audit_failures():
    """Компании, не прошедшие аудит данных, с дефектами по годам.

    Такая компания не попадает в скринер, а в списке компаний этого не видно:
    отчёты все помечены проверенными, и выглядит всё в порядке. Пометка в
    списке нужна, чтобы это было видно сразу, а не после вопроса «почему её
    нет в экране Грэма».
    """
    return data_audit.summary(data_audit.collect(set()))


@router.get("/data-sources")
def data_sources():
    """Состояние внешних источников и свежесть текущих цен.

    Предохранители (`utils/source_health.py`): работает ли источник, с какого
    момента молчит, когда следующая попытка и какой была последняя ошибка. Плюс
    сводка по ценам: сколько компаний сейчас на цене брокера, сколько на
    резервной с Мосбиржи и у скольких цена старше трёх дней.
    """
    from datetime import datetime, timezone

    from app.database import SessionLocal
    from app.models.company import Company
    from app.routers.prices_router import STALE_QUOTE
    from app.services.companies import logo_cache
    from app.utils.source_health import all_statuses

    db = SessionLocal()
    try:
        rows = db.query(Company.ticker, Company.price_source, Company.price_quoted_at,
                        Company.price_updated_at).all()
    finally:
        db.close()

    now = datetime.now(timezone.utc)
    by_source: dict = {}
    stale = []
    for ticker, source, quoted, updated in rows:
        key = source or ("tinvest" if updated else "нет цены")
        by_source[key] = by_source.get(key, 0) + 1
        at = quoted or updated
        if at is None or now - at > STALE_QUOTE:
            stale.append({"ticker": ticker, "quoted_at": at.isoformat() if at else None})
    stale.sort(key=lambda item: item["quoted_at"] or "")

    return {
        "sources": all_statuses(),
        "prices": {"companies": len(rows), "by_source": by_source,
                   "stale": len(stale), "stale_examples": stale[:15]},
        "logos": logo_cache.status(),
    }
