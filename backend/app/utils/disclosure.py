"""Когда отчёт стал известен рынку.

Опорная на графике, множители по дням и LTM переключаются на новый отчёт в день
его раскрытия. Взять этот день раньше — значит заглянуть вперёд, позже — держать
оценку по устаревшему отчёту. У Северстали годовой отчёт за 2025 год раскрыт
3 февраля 2026-го, а правило «конец года + 120 дней» держало оценку по 2024 году
до 30 апреля, пока прибыль уже рухнула вчетверо.

Порядок источников:

1. `disclosed_at` — фактическая дата из таблицы раскрытий e-disclosure;
2. `filing_date` — дата, которую модель извлекла из PDF (чаще всего дата
   аудиторского заключения). Заполнена у четырёх пятых годовых отчётов, но с
   мусором: встречается и −127 дней от конца года, и 788. Поэтому берётся
   только в правдоподобном окне;
3. `report_date`, если она отстоит от конца периода настолько, что может быть
   датой публикации (в базе это почти всегда дата баланса, см. ниже);
4. правило: конец периода + лаг. Лаг взят с запасом — ошибиться в большую
   сторону безопаснее: лишний месяц сдвинет ступень, заглядывание вперёд
   сделает ложной всю кривую.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

ANNUAL_LAG = timedelta(days=120)
INTERIM_LAG = timedelta(days=60)

# Насколько `report_date` должна отстоять от конца периода, чтобы её можно было
# принять за дату публикации. Поле в этой базе — дата баланса: у 1204 годовых
# отчётов из 1210 там стоит 31 декабря.
PUBLICATION_MIN_LAG = timedelta(days=30)

# Позже этого от конца периода отчёт не раскрывают — это повторная публикация
# или ошибка извлечения.
PUBLICATION_MAX_LAG = timedelta(days=540)


def period_end(fiscal_year: int, period_type: str) -> date:
    kind = str(getattr(period_type, "value", period_type)).upper()
    if kind == "SEMI_ANNUAL":
        return date(int(fiscal_year), 6, 30)
    return date(int(fiscal_year), 12, 31)


def default_disclosure(fiscal_year: int, period_type: str) -> date:
    """Дата по правилу — там, где фактической нет."""
    kind = str(getattr(period_type, "value", period_type)).upper()
    lag = INTERIM_LAG if kind == "SEMI_ANNUAL" else ANNUAL_LAG
    return period_end(fiscal_year, kind) + lag


def disclosed_on(report) -> date:
    """День, с которого отчёт можно использовать."""
    actual: Optional[date] = getattr(report, "disclosed_at", None)
    if actual is not None:
        return actual
    kind = getattr(report, "period_type", None) or "ANNUAL"
    end = period_end(report.fiscal_year, kind)
    filed = getattr(report, "filing_date", None)
    if filed is not None and PUBLICATION_MIN_LAG <= filed - end <= PUBLICATION_MAX_LAG:
        return filed
    published = getattr(report, "report_date", None)
    if published is not None and published - end >= PUBLICATION_MIN_LAG:
        return published
    return default_disclosure(report.fiscal_year, kind)


def disclosure_dates(db, company_id: int) -> dict:
    """(год, 'ANNUAL' | 'SEMI_ANNUAL') → день раскрытия, для всех отчётов компании."""
    from app.models.financial_report import FinancialReport

    if db is None:
        return {}
    rows = (
        db.query(FinancialReport)
        .filter(
            FinancialReport.company_id == company_id,
            FinancialReport.period_type.in_(("ANNUAL", "SEMI_ANNUAL")),
        )
        .all()
    )
    out: dict = {}
    for report in rows:
        kind = str(getattr(report.period_type, "value", report.period_type)).upper()
        key = (int(report.fiscal_year), kind)
        day = disclosed_on(report)
        # Несколько строк за период (разные стандарты) — берётся самая поздняя:
        # какая из них легла в ряд, отсюда не видно, а поздняя дата заглядывания
        # вперёд не даёт.
        if key not in out or day > out[key]:
            out[key] = day
    return out
