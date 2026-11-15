from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.admin import dev_sync_service as sync

router = APIRouter(prefix='/admin/dev-sync', tags=['admin'])


class ApplySnapshot(BaseModel):
    snapshot_id: str = Field(pattern=r'^[a-f0-9]{32}$')


@router.get('/status')
def status():
    return sync.status()


@router.post('/prepare', status_code=202)
def prepare():
    try:
        return sync.start('prepare')
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/apply', status_code=202)
def apply(body: ApplySnapshot):
    try:
        return sync.start('apply', body.snapshot_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
