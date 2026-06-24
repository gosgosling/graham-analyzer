"""Разрешение количества акций для капитализации и мультипликаторов."""

from __future__ import annotations

from typing import Optional, Protocol


class ShareCountSource(Protocol):
    shares_outstanding: Optional[int]
    shares_issued: Optional[int]
    shares_weighted_avg: Optional[int]
    treasury_shares: Optional[int]


def _fmt_shares(n: int) -> str:
    return f"{n:,}".replace(",", "\u202f")


def compute_circulation_shares(
    shares_outstanding: Optional[int],
    shares_issued: Optional[int],
    treasury_shares: Optional[int],
) -> Optional[int]:
    """
    Акции в обращении.

    Явное значение shares_outstanding имеет приоритет.
    Иначе: размещённые − казначейские (если заданы оба).
    """
    if shares_outstanding is not None:
        return int(shares_outstanding)

    issued = int(shares_issued) if shares_issued is not None else None
    if issued is None:
        return None

    if treasury_shares is not None:
        return max(issued - int(treasury_shares), 0)

    return None


def resolve_shares_for_multipliers(source: ShareCountSource) -> Optional[int]:
    """
    Количество акций для market cap / P/E / P/B.

    Приоритет: в обращении → средневзвешенное → размещённые (общее).
    """
    circulation = compute_circulation_shares(
        source.shares_outstanding,
        source.shares_issued,
        source.treasury_shares,
    )
    if circulation is not None:
        return circulation

    if source.shares_weighted_avg is not None:
        return int(source.shares_weighted_avg)

    if source.shares_issued is not None:
        return int(source.shares_issued)

    return None


def _legacy_duplicate_outstanding(source: ShareCountSource) -> bool:
    """
    После миграции в оба поля могли попасть одни и те же цифры из старого
    shares_outstanding. Если значения совпадают и нет средневзв./казначейских —
    считаем, что заполнено только «размещённое (общее)».
    """
    return (
        source.shares_outstanding is not None
        and source.shares_issued is not None
        and int(source.shares_outstanding) == int(source.shares_issued)
        and source.shares_weighted_avg is None
        and source.treasury_shares is None
    )


def explain_shares_cap_basis(
    source: ShareCountSource,
    shares_used: Optional[int],
) -> Optional[str]:
    """
    Пояснение, из какого поля отчёта взято количество акций для капитализации.

    Сопоставляет фактическое shares_used (из расчёта) с полями отчёта
    в том же порядке, что и resolve_shares_for_multipliers.
    """
    if shares_used is None:
        return None

    su = int(shares_used)
    fmt = _fmt_shares(su)

    circulation = compute_circulation_shares(
        source.shares_outstanding,
        source.shares_issued,
        source.treasury_shares,
    )

    has_outstanding = source.shares_outstanding is not None
    has_weighted = source.shares_weighted_avg is not None
    has_issued = source.shares_issued is not None
    legacy_dup = _legacy_duplicate_outstanding(source)

    if legacy_dup and has_issued and su == int(source.shares_issued):
        return (
            f"Использовано размещённое (общее) количество — {fmt} шт., "
            f"т.к. не указаны: акции в обращении, средневзвешенное количество."
        )

    if circulation is not None and su == circulation:
        if has_outstanding:
            return (
                f"Использованы акции в обращении — {fmt} шт.: "
                f"это предпочтительная база для расчёта капитализации."
            )
        issued_fmt = _fmt_shares(int(source.shares_issued))
        treasury_fmt = _fmt_shares(int(source.treasury_shares))
        return (
            f"Использованы акции в обращении — {fmt} шт. "
            f"(размещённые {issued_fmt} минус казначейские {treasury_fmt})."
        )

    if has_weighted and su == int(source.shares_weighted_avg):
        return (
            f"Использовано средневзвешенное количество — {fmt} шт., "
            f"т.к. в отчёте не указаны акции в обращении."
        )

    if has_issued and su == int(source.shares_issued):
        missing: list[str] = []
        if circulation is None:
            missing.append("акции в обращении")
        if not has_weighted:
            missing.append("средневзвешенное количество")
        if missing:
            return (
                f"Использовано размещённое (общее) количество — {fmt} шт., "
                f"т.к. не указаны: {', '.join(missing)}."
            )
        return f"Использовано размещённое (общее) количество — {fmt} шт."

    return f"Использовано {fmt} шт. для расчёта капитализации."


def resolve_shares_cap_basis(
    source: ShareCountSource,
    shares_used: Optional[int] = None,
) -> dict:
    """Метаданные базы капитализации для API."""
    count = shares_used if shares_used is not None else resolve_shares_for_multipliers(source)
    if count is None:
        return {"shares_used": None, "shares_cap_explanation": None}

    return {
        "shares_used": count,
        "shares_cap_explanation": explain_shares_cap_basis(source, count),
    }
