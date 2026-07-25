"""Нормализация дат из отчётов / ответа LLM.

Модель часто возвращает российский формат «30.04.2021» вместо ISO
«2021-04-30» — из-за этого create_report падал на strptime('%Y-%m-%d').
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d-%m-%Y",
)


def normalize_date_str(raw: Optional[Union[str, date]]) -> Optional[str]:
    """Привести дату к ISO YYYY-MM-DD или вернуть None."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw).strip()
    if not text or text.lower() in {"null", "none", "n/a", "-"}:
        return None
    # ISO с возможным временем: 2021-04-30T00:00:00
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text[:10]).isoformat()
        except ValueError:
            pass
    candidate = text[:10] if len(text) >= 10 else text
    for fmt in _FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(
        f"Не удалось разобрать дату {raw!r}. Ожидаются форматы "
        f"YYYY-MM-DD или DD.MM.YYYY."
    )


def parse_date(raw: Optional[Union[str, date]]) -> Optional[date]:
    """Строка/date → date; пустое → None."""
    iso = normalize_date_str(raw)
    if iso is None:
        return None
    return date.fromisoformat(iso)
