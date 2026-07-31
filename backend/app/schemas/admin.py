"""Схемы административных операций (бэкапы)."""
from pydantic import BaseModel


class PostgresBackupResponse(BaseModel):
    """Результат POST /admin/backup/postgres"""
    status: str = "ok"
    filename: str
    path: str
    size_bytes: int
    size_human: str
    message: str
