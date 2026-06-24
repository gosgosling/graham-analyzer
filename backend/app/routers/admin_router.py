from fastapi import APIRouter, HTTPException

from app.schemas import PostgresBackupResponse
from app.services.admin.backup_service import create_postgres_backup

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
