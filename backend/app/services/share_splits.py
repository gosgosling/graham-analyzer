"""
Дробления и консолидации акций.

Соглашение проекта: **всё хранится так, как было тогда**. Цена — как
торговалась в тот день, количество акций — как стояло в отчёте. Приведение к
сегодняшней шкале не годится: после следующего сплита пришлось бы
пересчитывать всю историю заново, а отчёты эмитента при этом не меняются.

Из этого следует, где именно проходит опасное место. Мосбиржа исторические
цены задним числом не пересчитывает — то есть цены она отдаёт ровно так, как
нам нужно. А вот `ISSUESIZE` в её реестре всегда **сегодняшний**, и подставить
его в отчёт за прошлый год после сплита значит завысить количество акций в
`ratio` раз, а вместе с ним и капитализацию.

Пример. Т-Технологии раздробили акции 10:1 17 апреля 2026 года: 16.04 бумага
стоила 3 196,8 ₽, 17.04 — 325,7 ₽. Для отчёта за 2025 год правильны цена
3 277,6 ₽ и 268 274 786 акций. Реестр же сегодня показывает 2 682 747 860 —
это число после дробления, и в отчёт за 2025-й оно не годится.

Здесь лежит арифметика перевода сегодняшнего выпуска в тогдашний.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, Sequence

# Известные дробления: тикер → список {дата, коэффициент}.
#
# `date` — первый торговый день в новом масштабе (день, когда цена в истории
# ISS падает скачком). `ratio` — во сколько раз выросло число акций: 10 для
# дробления 10:1, 0.1 для обратной консолидации 1:10.
#
# Справочник — заготовка для первичного заполнения; рабочие данные живут
# в `companies.share_splits`. Найти новые можно скриптом
# `scripts/detect_share_splits.py`: он ищет разрывы в истории котировок.
KNOWN_SPLITS: dict[str, list[dict[str, Any]]] = {
    # МКПАО «Т-Технологии», дробление 10:1. Проверено по истории ISS:
    # 2026-04-16 закрытие 3 196,8 ₽ → 2026-04-17 закрытие 325,7 ₽.
    "T": [{"date": "2026-04-17", "ratio": 10}],
}


def normalize_splits(raw: Any) -> list[dict[str, Any]]:
    """
    Приводит хранимое значение к списку `{"date": ..., "ratio": ...}`.

    Мусор отбрасывается молча: одна кривая запись не должна ломать расчёт
    капитализации по всей компании. Нулевой и отрицательный коэффициент
    отбрасывается тоже — на него нельзя делить.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        when = item.get("date")
        ratio = item.get("ratio")
        if isinstance(when, date):
            when = when.isoformat()
        if not isinstance(when, str):
            continue
        try:
            date.fromisoformat(when[:10])
        except ValueError:
            continue
        try:
            ratio_f = float(ratio)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if ratio_f <= 0:
            continue
        result.append({"date": when[:10], "ratio": ratio_f})

    result.sort(key=lambda x: x["date"])
    return result


def shares_factor(splits: Any, target_date: Optional[date]) -> float:
    """
    Во сколько раз сегодняшнее число акций больше тогдашнего.

    Перемножает коэффициенты всех дроблений, случившихся **после** целевой
    даты. Дробления до неё уже учтены в отчёте за тот период и трогать их
    нельзя.

    >>> splits = [{"date": "2026-04-17", "ratio": 10}]
    >>> shares_factor(splits, date(2025, 12, 31))
    10.0
    >>> shares_factor(splits, date(2026, 12, 31))
    1.0
    """
    if target_date is None:
        return 1.0

    factor = 1.0
    for entry in normalize_splits(splits):
        if date.fromisoformat(entry["date"]) > target_date:
            factor *= entry["ratio"]
    return factor


def shares_at_date(
    current_issuesize: Optional[int],
    splits: Any,
    target_date: Optional[date],
) -> Optional[int]:
    """
    Сегодняшний выпуск → выпуск на целевую дату.

    >>> shares_at_date(2_682_747_860, [{"date": "2026-04-17", "ratio": 10}],
    ...                date(2025, 12, 31))
    268274786
    """
    if current_issuesize is None:
        return None
    factor = shares_factor(splits, target_date)
    if factor == 1.0:
        return int(current_issuesize)
    return int(round(current_issuesize / factor))


def price_scale_hint(splits: Any, target_date: Optional[date]) -> Optional[str]:
    """
    Предупреждение о смене масштаба, если между датой и сегодня был сплит.

    Цену править не нужно — Мосбиржа отдаёт её как торговалось. Но человек,
    глядящий на 3 277 ₽ при нынешних 283 ₽, должен понимать, почему.
    """
    entries = [
        e for e in normalize_splits(splits)
        if target_date is not None and date.fromisoformat(e["date"]) > target_date
    ]
    if not entries:
        return None

    parts = []
    for entry in entries:
        ratio = entry["ratio"]
        if ratio >= 1:
            shown = int(ratio) if float(ratio).is_integer() else ratio
            parts.append(f"дробление {shown}:1 от {entry['date']}")
        else:
            shown = int(round(1 / ratio))
            parts.append(f"консолидация 1:{shown} от {entry['date']}")
    return (
        "После этой даты был сплит (" + ", ".join(parts) + "). "
        "Цена и количество акций хранятся так, как было тогда, — "
        "с сегодняшними они не сравниваются напрямую."
    )


def seed_splits(ticker: str) -> Optional[list[dict[str, Any]]]:
    """Известные дробления для тикера — или None, если их нет."""
    entries = KNOWN_SPLITS.get(ticker.upper())
    return [dict(e) for e in entries] if entries else None


__all__: Sequence[str] = (
    "KNOWN_SPLITS",
    "normalize_splits",
    "price_scale_hint",
    "seed_splits",
    "shares_at_date",
    "shares_factor",
)
