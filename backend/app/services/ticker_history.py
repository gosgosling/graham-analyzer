"""
Прежние тикеры компании.

Мосбиржа хранит историю торгов под тем символом, под которым бумага торговалась
в тот день, и связи между старым и новым тикером в ISS нет: у Яндекса сменился
даже ISIN (NL0009805522 → RU000A107T19). Поэтому запрос цены за 2022 год по
тикеру YDEX возвращает пустоту — не потому, что цены нет, а потому, что тогда
её звали YNDX.

Здесь лежит соответствие «дата → под каким символом искать» и справочник
известных переименований для первичного заполнения.

Отдельно стоит различать два похожих случая:

* **Смена тикера** — цена есть, лежит под другим именем. Лечится этим модулем.
* **Отчёт старше IPO** — цены не существует вовсе, и выдумывать её нельзя.
  Такой случай определяется по дате первой сделки (`get_first_trade_date`).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Optional, Sequence

# Известные переименования на Мосбирже: новый тикер → цепочка прежних.
#
# `until` — последний день, когда бумага торговалась под этим символом
# (проверено по истории ISS). Цепочка может быть длиннее одного звена:
# ОГК-4 → Э.ОН Россия → Юнипро — это три символа у одной компании.
#
# Справочник нужен только для первичного заполнения: рабочие данные живут
# в `companies.former_tickers`, потому что переименования продолжаются.
KNOWN_TICKER_CHANGES: dict[str, list[dict[str, str]]] = {
    # Редомициляция 2024: Yandex N.V. → МКПАО «Яндекс»
    "YDEX": [{"ticker": "YNDX", "until": "2024-07-07"}],
    # Редомициляция 2024: TCS Group → МКПАО «Т-Технологии»
    "T": [{"ticker": "TCSG", "until": "2024-11-27"}],
    # Редомициляция 2024–2025: X5 Retail Group N.V. → ПАО «Корпоративный центр ИКС 5»
    "X5": [{"ticker": "FIVE", "until": "2024-11-22"}],
    # Редомициляция 2024: HeadHunter Group PLC → МКПАО «Хэдхантер»
    "HEAD": [{"ticker": "HHRU", "until": "2024-09-27"}],
    # Редомициляция 2021: Mail.ru Group → МКПАО «ВК»
    "VKCO": [{"ticker": "MAIL", "until": "2021-12-13"}],
    # Ребрендинг 2023: «Энел Россия» → «Эл5-Энерго»
    "ELFV": [{"ticker": "ENRU", "until": "2023-03-28"}],
    # Ребрендинг 2023: «Институт стволовых клеток человека» → «Артген биотех»
    "ABIO": [{"ticker": "ISKJ", "until": "2023-08-17"}],
    # Ребрендинг 2022: «Русолово» → «Росолово»
    "ROLO": [{"ticker": "RUSP", "until": "2022-06-15"}],
    # ОГК-4 → Э.ОН Россия → Юнипро
    "UPRO": [
        {"ticker": "EONR", "until": "2016-06-30"},
        {"ticker": "OGKD", "until": "2007-04-24"},
    ],
}


def normalize_former_tickers(raw: Any) -> list[dict[str, str]]:
    """
    Приводит хранимое значение к списку `{"ticker": ..., "until": ...}`.

    Данные приходят из JSON-колонки и из формы редактирования, поэтому
    заведомо мусорные элементы отбрасываются молча: одна опечатка не должна
    ронять запрос цены по всей компании.
    """
    if not isinstance(raw, (list, tuple)):
        return []

    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ticker = item.get("ticker")
        until = item.get("until")
        if not isinstance(ticker, str) or not ticker.strip():
            continue
        if isinstance(until, date):
            until = until.isoformat()
        if not isinstance(until, str):
            continue
        try:
            date.fromisoformat(until[:10])
        except ValueError:
            continue
        result.append({"ticker": ticker.strip().upper(), "until": until[:10]})

    # По возрастанию даты: первое подходящее звено и будет нужным.
    result.sort(key=lambda x: x["until"])
    return result


def resolve_ticker(
    current_ticker: str,
    former_tickers: Any,
    target_date: Optional[date],
) -> str:
    """
    Под каким символом искать котировку на `target_date`.

    Берётся самое раннее звено, чей `until` ещё не наступил на целевую дату;
    если таких нет — бумага в тот день уже торговалась под нынешним именем.

    >>> hist = [{"ticker": "EONR", "until": "2016-06-30"},
    ...         {"ticker": "OGKD", "until": "2007-04-24"}]
    >>> resolve_ticker("UPRO", hist, date(2013, 12, 31))
    'EONR'
    >>> resolve_ticker("UPRO", hist, date(2006, 12, 31))
    'OGKD'
    >>> resolve_ticker("UPRO", hist, date(2020, 12, 31))
    'UPRO'
    """
    if target_date is None:
        return current_ticker

    for entry in normalize_former_tickers(former_tickers):
        if target_date <= date.fromisoformat(entry["until"]):
            return entry["ticker"]

    return current_ticker


def ticker_chain(current_ticker: str, former_tickers: Any) -> list[str]:
    """
    Все символы компании от нынешнего к самому старому.

    Нужен, когда дата неизвестна и остаётся перебрать варианты — например
    при поиске количества акций или дивидендов за давний период.
    """
    former = normalize_former_tickers(former_tickers)
    return [current_ticker] + [e["ticker"] for e in reversed(former)]


def seed_former_tickers(ticker: str) -> Optional[list[dict[str, str]]]:
    """Известные переименования для тикера — или None, если их нет."""
    entries = KNOWN_TICKER_CHANGES.get(ticker.upper())
    return [dict(e) for e in entries] if entries else None


def describe_chain(current_ticker: str, former_tickers: Any) -> str:
    """Человекочитаемая цепочка для сообщений об ошибке и логов."""
    former = normalize_former_tickers(former_tickers)
    if not former:
        return current_ticker
    parts: list[str] = []
    for entry in former:
        parts.append(f"{entry['ticker']} (по {entry['until']})")
    parts.append(current_ticker)
    return " → ".join(parts)


__all__: Sequence[str] = (
    "KNOWN_TICKER_CHANGES",
    "describe_chain",
    "normalize_former_tickers",
    "resolve_ticker",
    "seed_former_tickers",
    "ticker_chain",
)
