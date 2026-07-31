"""Схемы анализа непрерывности дивидендов."""
from typing import List, Optional

from pydantic import BaseModel


class DividendContinuityResult(BaseModel):
    """Результат анализа непрерывности выплаты дивидендов"""
    company_id: int
    dividend_start_year: Optional[int] = None
    years_of_continuous_payments: int  # Количество лет непрерывных выплат
    is_continuous: bool  # Выплачиваются ли дивиденды непрерывно
    last_payment_year: Optional[int] = None
    gap_years: List[int] = []  # Годы, когда дивиденды не выплачивались
    recommendation: str  # Рекомендация на основе непрерывности
