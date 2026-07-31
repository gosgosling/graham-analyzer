"""Список торгуемых бумаг с Мосбиржи.

Раньше здесь же жили `/analysis`, `/{id}`, `/{id}/multipliers` и `/{id}/result`,
отдававшие захардкоженные mock-данные трёх компаний из времён этапа «сначала
заглушки, потом БД». Фронтенд их не вызывал, но наружу они торчали и гоняли
настоящий `classify_company` по выдуманным цифрам. Реальный анализ живёт в
`/companies` и `/multipliers`.
"""
from fastapi import APIRouter, HTTPException, status

from app.schemas import Security
from app.utils.moex_client import MoexUnavailableError, get_moex_securities

router = APIRouter(prefix="/securities", tags=["securities"])


@router.get("/", response_model=list[Security])
def get_securities():
    """Акции основного режима торгов (TQBR).

    Недоступность MOEX отдаётся как 503, а не пустым списком: пустая таблица
    выглядит как «бумаг нет» и заставляет искать причину в приложении.
    """
    try:
        return get_moex_securities()
    except MoexUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"MOEX ISS недоступен: {exc}",
        ) from exc
