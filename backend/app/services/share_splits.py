"""
Дробления и консолидации акций.

Соглашение проекта: **всё хранится так, как было тогда**. Цена — как
торговалась в тот день, количество акций — как стояло в отчёте. Приведение к
сегодняшней шкале не годится: после следующего сплита пришлось бы
пересчитывать всю историю заново, а отчёты эмитента при этом не меняются.

Опасных места два. `ISSUESIZE` в реестре Мосбиржи всегда **сегодняшний**, и
подставить его в отчёт за прошлый год после дробления значит завысить
количество акций в `ratio` раз, а вместе с ним и капитализацию. А историю
цен и дивидендов Мосбиржа на дробления из своего списка пересчитывает задним
числом (проверено на Т, Норникеле, Полюсе, Транснефти, ВТБ, Русагро) — эти
цены надо вернуть к торговавшимся, см. `market/split_scale.py`.

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


def report_split_factor(
    splits: Any,
    report_date: Optional[date],
    report_shares: Optional[float],
    current_shares: Optional[float],
) -> float:
    """
    Как `shares_factor`, но с поправкой на отчёты, уже пересчитанные эмитентом.

    По МСФО (IAS 33) дробление, случившееся после отчётной даты, но до
    выпуска отчёта, пересчитывается в нём задним числом. Отчёт Транснефти за
    2023 год датирован 31 декабря, дробление 100:1 — 21 февраля 2024-го, а
    акций в отчёте уже 725 млн, новых. Делить его по дате ещё на сто значит
    получить прибыль на акцию в сто раз меньше настоящей.

    Шкалу отчёта поэтому выдаёт его собственное число акций: если оно ближе
    к нынешнему, чем умноженное на коэффициент, — отчёт уже в новой шкале.

    >>> report_split_factor([{"date": "2024-02-21", "ratio": 100}], date(2023, 12, 31), 724_934_300, 724_934_300)
    1.0
    >>> report_split_factor([{"date": "2024-02-21", "ratio": 100}], date(2023, 12, 31), 7_249_343, 724_934_300)
    100.0
    """
    import math

    factor = shares_factor(splits, report_date)
    if factor == 1.0 or not report_shares or not current_shares:
        return factor
    as_is = abs(math.log(float(report_shares) / float(current_shares)))
    scaled = abs(math.log(float(report_shares) * factor / float(current_shares)))
    return 1.0 if as_is < scaled else factor


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
        "После этой даты менялось число акций (" + ", ".join(parts) + "). "
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
    "report_split_factor",
    "seed_splits",
    "shares_at_date",
    "shares_factor",
)


def company_splits(db: Any, company: Any) -> list[dict[str, Any]]:
    """
    Все известные дробления компании: из карточки и из событий Мосбиржи.

    В карточке (`companies.share_splits`) лежит то, что внесли вручную или
    скриптом: Мосбиржа дробление Белуги 8:1 в своём списке не держит. В
    событиях (`corporate_events`, вид `split`) — то, что Мосбиржа отдаёт по
    `splits.json`: Норникель, Полюс, Транснефть, ВТБ. Одна и та же дата из
    обоих источников считается один раз; при расхождении верим карточке —
    её правят руками.
    """
    from app.models.corporate_event import CorporateEvent

    merged: dict[str, dict[str, Any]] = {}
    events = (
        db.query(CorporateEvent)
        .filter(CorporateEvent.company_id == company.id, CorporateEvent.kind == "split")
        .all()
    )
    for event in events:
        if event.value is not None and float(event.value) > 0:
            merged[event.date.isoformat()] = {"date": event.date.isoformat(), "ratio": float(event.value)}
    for entry in normalize_splits(getattr(company, "share_splits", None)):
        merged[entry["date"]] = entry
    return normalize_splits(list(merged.values()))


def align_report_scale(
    price: Optional[float],
    shares: Optional[float],
    factor: float,
    traded_price: Optional[float],
    current_shares: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """
    Цену и акции отчёта — в одну шкалу: «как торговалось на дату отчёта».

    `factor` — во сколько раз выросло число акций после отчётной даты. Если
    дроблений после неё не было, приводить нечего. Иначе каждая из двух
    величин могла попасть в отчёт в любой шкале, и смесь даёт капитализацию
    в `factor` раз мимо:

    * Русолово, 2012–2022: размещённых акций 30 млрд — нынешний выпуск из
      реестра, а цена тогдашняя. P/B 59 вместо 5,9.
    * Полюс, 2024: отчёт вышел после дробления, акции эмитент пересчитал
      (IAS 33), цена осталась тогдашней. P/E 43 вместо 4,3.
    * Транснефть, 2023: и цена, и акции уже новые — сходятся между собой,
      но для общей шкалы их тоже переводим обратно.

    Шкала акций — по нынешнему числу: что ближе, само число или умноженное на
    коэффициент. Шкала цены — по цене как торговалась в тот день (история
    цен хранится так): ближе она сама или делённая на коэффициент.

    >>> align_report_scale(7.802, 30_001_000_000, 10, 7.8, 30_001_000_000)
    (7.802, 3000100000.0)
    >>> align_report_scale(1450.0, 724_934_300, 100, 145_000.0, 724_934_300)
    (145000.0, 7249343.0)
    >>> align_report_scale(3277.6, 257_393_950, 10, 3277.6, 2_549_948_000)
    (3277.6, 257393950)
    """
    import math

    if factor == 1.0:
        return price, shares

    if shares and current_shares:
        if abs(math.log(float(shares) / float(current_shares))) < abs(math.log(float(shares) * factor / float(current_shares))):
            shares = float(shares) / factor
    if price and traded_price:
        if abs(math.log(float(price) * factor / float(traded_price))) < abs(math.log(float(price) / float(traded_price))):
            price = float(price) * factor
    return price, shares


def current_share_count(db: Any, company_id: int, splits: Any) -> Optional[float]:
    """Нынешнее число акций — по самому свежему отчёту любого периода,
    приведённому к сегодняшней шкале.

    Брать последний **годовой** нельзя: у Т годовой за 2025-й вышел до
    дробления (257 млн акций), и рядом с ним все прошлые отчёты выглядели
    «уже пересчитанными» — P/B на графике падал вдесятеро. Полугодие 2026-го
    уже после дробления: 2,55 млрд.
    """
    from app.models.financial_report import FinancialReport

    latest = (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id,
                (FinancialReport.shares_outstanding.isnot(None)) | (FinancialReport.shares_issued.isnot(None)))
        .order_by(FinancialReport.report_date.desc())
        .first()
    )
    if latest is None:
        return None
    shares = latest.shares_outstanding or latest.shares_issued
    return float(shares) * shares_factor(splits, latest.report_date)


def today_share_count(report: Any, issue_size: Optional[int], factor: float = 1.0,
                      max_seen: Optional[float] = None) -> Optional[tuple[float, str]]:
    """
    Акции в обращении сегодня — если выпуск после отчёта изменился.

    `issue_size` — выпуск по реестру Мосбиржи сегодня, `factor` — дробления
    после даты отчёта. Возвращает (акции, пояснение) или None, если отчётное
    число годится и сегодня.

    Два случая:

    * **Выпуск вырос после отчёта** (допэмиссия, SPO): сегодня в реестре
      больше акций, чем было во всех отчётах компании (`max_seen` — наибольшее
      число из них в сегодняшней шкале). К акциям в обращении прибавляется
      разница. Сравнивать только с последним отчётом нельзя: у Астры,
      Глоракса, РуссНефти «размещённые» в отчёте записаны без казначейских, и
      выкуп выглядел бы допэмиссией.
    * **Размещённых в отчёте уже сегодняшнее число, а в обращении — вдвое
      меньше, и казначейскими это не объяснить.** Так у ВТБ: отчёт за 2025
      год — 6,54 млрд в обращении, а 12,93 млрд размещённых попали в отчёт из
      сегодняшнего реестра, после конвертации префов в апреле 2026. Если
      казначейские в отчёте указаны, разрыв сверх них — новый выпуск.

    Если казначейские не указаны, разрыв между размещёнными и обращением
    считается казначейским (Белуга, МТС) — так безопаснее, чем завысить.

    >>> class R: shares_outstanding, shares_issued, treasury_shares = 6_540_634_652, 12_927_766_416, 79_783_631
    >>> round(today_share_count(R, 12_927_766_416)[0])
    12847982785
    >>> class E: shares_outstanding, shares_issued, treasury_shares = 383_445_362, 383_445_362, None
    >>> round(today_share_count(E, 783_179_820)[0])
    783179820
    >>> class B: shares_outstanding, shares_issued, treasury_shares = 87_460_000, 126_400_000, None
    >>> today_share_count(B, 126_400_000) is None
    True
    >>> class A: shares_outstanding, shares_issued, treasury_shares = 201_358_879, 201_358_879, None
    >>> today_share_count(A, 210_000_000, max_seen=210_000_000) is None   # выкуп, а не допэмиссия
    True
    """
    if not issue_size:
        return None
    outstanding = getattr(report, "shares_outstanding", None)
    issued = getattr(report, "shares_issued", None)
    treasury = getattr(report, "treasury_shares", None)
    base = float(outstanding or issued or 0) * factor
    if base <= 0:
        return None
    issued_f = float(issued) * factor if issued else None
    treasury_f = float(treasury) * factor if treasury else None
    today = float(issue_size)

    ceiling = max(issued_f or 0, max_seen or 0)
    if issued_f is not None and today > ceiling * 1.02:
        result = base + (today - issued_f)
        why = (f"после отчёта выпуск вырос: по реестру Мосбиржи сейчас {int(today):,} акций "
               f"против {int(issued_f):,} в отчёте").replace(",", "\u202f")
        return result, why
    if treasury_f is not None and outstanding and issued_f is not None:
        gap = issued_f - treasury_f - float(outstanding) * factor
        if gap > 0.05 * issued_f and abs(today - issued_f) <= 0.02 * issued_f:
            result = today - treasury_f
            why = (f"после отчёта выпуск изменился: по реестру Мосбиржи сейчас {int(today):,} акций, "
                   f"за вычетом казначейских — {int(result):,}").replace(",", "\u202f")
            return result, why
    return None


def moex_known_splits(db: Any, company_id: int) -> set[str]:
    """Даты дроблений, которые Мосбиржа ведёт сама (её splits.json).

    На них она пересчитывает задним числом и историю цен, и суммы дивидендов:
    у Норникеля, Полюса, Транснефти, ВТБ, Т это проверено по данным. Дробление,
    которого в её списке нет (Белуга 8:1), в её данных не учтено.
    """
    from app.models.corporate_event import CorporateEvent

    rows = (
        db.query(CorporateEvent.date)
        .filter(CorporateEvent.company_id == company_id, CorporateEvent.kind == "split",
                CorporateEvent.source == "moex")
        .all()
    )
    return {row[0].isoformat() for row in rows}


def split_note(splits: Any) -> Optional[str]:
    """Подпись к графику: какие цены приведены и к чему."""
    entries = normalize_splits(splits)
    if not entries:
        return None
    parts = []
    for entry in entries:
        ratio = entry["ratio"]
        day = date.fromisoformat(entry["date"]).strftime("%d.%m.%Y")
        if ratio >= 1:
            shown = int(ratio) if float(ratio).is_integer() else ratio
            parts.append(f"дробление {shown}:1 от {day}")
        else:
            shown = int(round(1 / ratio))
            parts.append(f"консолидация 1:{shown} от {day}")
    return (
        "Цены до " + ("этих событий" if len(entries) > 1 else
                      "консолидации" if entries[0]["ratio"] < 1 else "дробления")
        + " приведены к нынешнему числу акций (" + ", ".join(parts) + ")."
    )
