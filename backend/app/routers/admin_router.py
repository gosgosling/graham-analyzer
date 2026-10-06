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
