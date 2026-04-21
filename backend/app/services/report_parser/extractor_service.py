"""Пайплайн: PDF → текст → LLM → валидация → запись отчёта в БД.

Используется:
  * эндпоинтом POST /reports/parse-pdf (в reports_router.py),
  * CLI-утилитой tools/report-parser/main.py.

Для LLM используется `app.config.settings` (LLM_*).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.config import settings
from app.models.company import Company
from app.models.enums import sector_to_report_type
from app.models.financial_report import FinancialReport
from app.schemas import FinancialReportCreate
from app.services.reports import report_service
from app.services.report_parser.llm_client import (
    LLMNotConfiguredError,
    LLMParseError,
    LLMTransientError,
    extract_report_via_llm,
)
from app.services.report_parser.pdf_extractor import (
    PdfExtractionResult,
    extract_financial_pages,
)
from app.services.report_parser.prompts import build_system_prompt, build_user_prompt
from app.services.report_parser.schemas import ExtractedReport, rescale_to_millions
from app.utils.moex_client import (
    get_closing_price_on_or_before,
    get_fx_rate_on_or_before,
)

logger = logging.getLogger(__name__)


# ─── Описание сравниваемых полей ─────────────────────────────────────────────


@dataclass(frozen=True)
class _FieldSpec:
    """Одно поле отчёта — как его сравнивать и показывать."""
    key: str                    # имя атрибута в FinancialReport И в ExtractedReport
    label: str                  # человеко-читаемое имя
    kind: str                   # 'money_mln' | 'int' | 'float' | 'bool' | 'str' | 'date'
    relevant_for: tuple[str, ...] = ("general", "bank")  # general/bank


# Поля, которые есть и в модели БД, и в ExtractedReport — значит их реально
# можно сравнивать. Порядок важен — в таком порядке покажем в UI.
_COMPARABLE_FIELDS: tuple[_FieldSpec, ...] = (
    _FieldSpec("report_date", "Дата окончания периода", "date"),
    _FieldSpec("filing_date", "Дата публикации", "date"),
    _FieldSpec("currency", "Валюта", "str"),
    _FieldSpec("shares_outstanding", "Акции в обращении", "int"),
    _FieldSpec("revenue", "Выручка / Опер. доходы", "money_mln"),
    _FieldSpec("net_income", "Чистая прибыль", "money_mln"),
    _FieldSpec("net_income_reported", "Прибыль (отчётная)", "money_mln"),
    _FieldSpec("total_assets", "Активы (всего)", "money_mln"),
    _FieldSpec("current_assets", "Оборотные активы", "money_mln", ("general",)),
    _FieldSpec("total_liabilities", "Обязательства (всего)", "money_mln"),
    _FieldSpec("current_liabilities", "Краткосрочные обязательства", "money_mln", ("general",)),
    _FieldSpec("equity", "Собственный капитал", "money_mln"),
    _FieldSpec("dividends_per_share", "Дивиденд на акцию", "float"),
    _FieldSpec("dividends_paid", "Дивиденды выплачивались", "bool"),
    _FieldSpec("net_interest_income", "Чистые проц. доходы (NII)", "money_mln", ("bank",)),
    _FieldSpec("fee_commission_income", "Чистые комисс. доходы", "money_mln", ("bank",)),
    _FieldSpec("operating_expenses", "Операционные расходы", "money_mln", ("bank",)),
    _FieldSpec("provisions", "Резервы под обесценение", "money_mln", ("bank",)),
)


_MATERIAL_MONEY_THRESHOLD_MLN = 1.0  # разница в < 1 млн не считаем значимой
_MATERIAL_PCT_THRESHOLD = 0.5        # < 0.5% — это копейки округления

Status = str  # 'match' | 'close' | 'mismatch' | 'missing_ai' | 'missing_existing' | 'both_missing'


@dataclass
class ReportFieldDiff:
    """Diff по одному полю — что было, что извлекла модель, насколько совпало."""
    field: str
    label: str
    kind: str
    existing_value: Any
    extracted_value: Any
    abs_diff: Optional[float] = None     # |A - B|, только для числовых
    pct_diff: Optional[float] = None     # (A - B) / A * 100, знак = насколько модель ЗАВЫСИЛА
    status: Status = "match"
    note: Optional[str] = None


@dataclass
class ComparisonSummary:
    """Общая сводка по сравнению."""
    total_fields: int = 0
    matched: int = 0
    close: int = 0          # числа отличаются < 1%, но не 0
    mismatched: int = 0
    missing_in_ai: int = 0  # у аналитика значение есть, AI не нашёл
    missing_in_existing: int = 0  # у AI значение есть, у аналитика не заполнено
    both_missing: int = 0
    max_pct_diff: Optional[float] = None


@dataclass
class ComparisonResult:
    """Результат режима сравнения (compare-only, без записи в БД)."""
    ticker: str
    fiscal_year: int
    report_type: str
    existing_report_id: int
    existing_report_verified: bool
    extracted: ExtractedReport
    diffs: list[ReportFieldDiff] = field(default_factory=list)
    summary: ComparisonSummary = field(default_factory=ComparisonSummary)
    pdf_label: str = ""
    selected_pages: int = 0
    total_pages: int = 0


# ─── Результат ────────────────────────────────────────────────────────────────


@dataclass
class ExtractionOutcome:
    """Что получилось после обработки одного PDF."""
    ticker: str
    fiscal_year: int
    report_type: str  # 'general' | 'bank'
    dry_run: bool
    pdf_label: str
    skipped_reason: Optional[str] = None
    created_report_id: Optional[int] = None
    extracted: Optional[ExtractedReport] = None
    selected_pages: int = 0
    total_pages: int = 0

    @property
    def success(self) -> bool:
        return self.skipped_reason is None and (
            self.dry_run or self.created_report_id is not None
        )


# ─── Исключения ──────────────────────────────────────────────────────────────


class ReportAlreadyExistsError(RuntimeError):
    """В БД уже есть отчёт с такими ключевыми атрибутами (без --force)."""

    def __init__(self, report_id: int):
        super().__init__(
            f"Отчёт уже существует в БД (id={report_id}). "
            f"Используй force=True чтобы пересоздать."
        )
        self.report_id = report_id


# ─── Вспомогательные ─────────────────────────────────────────────────────────


def _resolve_report_date(extracted: ExtractedReport) -> str:
    """Если модель не смогла извлечь report_date — подставим 31.12 года."""
    if extracted.report_date:
        return extracted.report_date
    return f"{extracted.fiscal_year}-12-31"


def _parse_iso_date(raw: Optional[str]) -> Optional[date]:
    """Попытка распарсить YYYY-MM-DD. Возвращает None если формат неожиданный."""
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except (ValueError, TypeError):
        return None


def _fetch_moex_price_for_report(
    ticker: Optional[str], target: Optional[date],
) -> Optional[float]:
    """Тихо запросить у MOEX цену закрытия на дату (или ближайший торговый день).

    Используется при AI-парсинге, чтобы сразу заполнить price_per_share /
    price_at_filing и сразу посчитать мультипликаторы без ручных кликов.
    """
    if not ticker or target is None:
        return None
    try:
        info = get_closing_price_on_or_before(ticker, target)
    except Exception as exc:  # noqa: BLE001 — внешний HTTP, падать не имеем права
        logger.warning(
            "MOEX price lookup failed for %s @ %s: %s", ticker, target, exc,
        )
        return None
    if not info or info.get("price") is None:
        return None
    try:
        return float(info["price"])
    except (TypeError, ValueError):
        return None


def _enrich_with_moex_prices(
    extracted: ExtractedReport,
    *,
    ticker: Optional[str],
    exchange_rate: Optional[float] = None,
) -> tuple[Optional[float], Optional[float]]:
    """Вернуть (price_per_share, price_at_filing) из MOEX для данного отчёта.

    * price_per_share — цена на report_date (конец отчётного периода);
    * price_at_filing — цена на filing_date (день публикации отчёта).

    ⚠️ MOEX всегда возвращает цену в рублях (акции на MOEX торгуются только
    в RUB). Но инвариант проекта — все денежные поля отчёта хранятся в
    `report.currency` и потом единообразно умножаются на `exchange_rate` в
    `calc_multipliers.to_rub_full(...)`. Поэтому если отчёт в иностранной
    валюте и `exchange_rate` известен, делим цену MOEX на курс, чтобы положить
    её в поле в валюте отчёта. Без этой конвертации P/E и P/B уйдут в космос
    (price × exchange_rate × shares вместо price × shares).

    Оба значения — best-effort: если MOEX недоступен, даты неизвестны или
    `exchange_rate` отсутствует для non-RUB отчёта — возвращаем None. Тогда
    пользователь сможет ввести цену вручную через форму.
    """
    report_iso = _resolve_report_date(extracted)
    report_d = _parse_iso_date(report_iso)
    filing_d = _parse_iso_date(extracted.filing_date)

    price_on_report_rub = _fetch_moex_price_for_report(ticker, report_d)
    price_on_filing_rub = _fetch_moex_price_for_report(ticker, filing_d)

    # Для RUB-отчёта возвращаем цены как есть.
    currency = (extracted.currency or "RUB").upper()
    if currency == "RUB":
        return price_on_report_rub, price_on_filing_rub

    # Для non-RUB отчёта без курса не можем безопасно конвертировать — лучше
    # оставить поля пустыми, чтобы не записать рубли под ценник валюты.
    if not exchange_rate or exchange_rate <= 0:
        if price_on_report_rub is not None or price_on_filing_rub is not None:
            logger.warning(
                "MOEX вернул цену в RUB для отчёта %s, но exchange_rate неизвестен — "
                "цена не будет подставлена автоматически.", currency,
            )
        return None, None

    def _to_report_currency(price_rub: Optional[float]) -> Optional[float]:
        if price_rub is None:
            return None
        return round(price_rub / exchange_rate, 4)

    return _to_report_currency(price_on_report_rub), _to_report_currency(price_on_filing_rub)


def _fetch_fx_rate_for_report(
    currency: Optional[str], target: Optional[date],
) -> Optional[float]:
    """Best-effort подтяжка курса иностранной валюты к рублю на дату отчёта.

    Источник — `get_fx_rate_on_or_before` (MOEX → CBR fallback). Возвращает
    только число курса; при отсутствии данных или любой сетевой ошибке
    возвращает None (в этом случае отчёт всё равно будет сохранён и пользователь
    сможет ввести курс вручную в форме).
    """
    if not currency or currency.upper() == "RUB" or target is None:
        return None
    try:
        info = get_fx_rate_on_or_before(currency.upper(), target)
    except Exception as exc:  # noqa: BLE001 — внешний HTTP, падать не имеем права
        logger.warning(
            "FX rate lookup failed for %s @ %s: %s", currency, target, exc,
        )
        return None
    if not info or info.get("rate") is None:
        return None
    try:
        rate = float(info["rate"])
    except (TypeError, ValueError):
        return None
    return rate if rate > 0 else None


# Порог, ниже которого shares_outstanding считается подозрительно малым для
# крупного публичного эмитента MOEX. Практически все крупные российские эмитенты
# имеют > 10 млн акций; значения < 10 млн обычно означают, что модель не учла
# подпись '(тыс. штук)' рядом с таблицей EPS.
_SUSPICIOUS_SHARES_THRESHOLD = 10_000_000

# «Мягкий» порог — между ним и _SUSPICIOUS_SHARES_THRESHOLD мы НЕ делаем
# auto-fix (риск false positive для мелких эмитентов типа Транснефти), но пишем
# предупреждение в extraction_notes: «сверь с MOEX». Русгидро (~444 млрд акций,
# подано в отчёте '(тыс. штук)' → модель легко может выдать 440 млн) — как раз
# этот случай.
_SHARES_SOFT_WARN_THRESHOLD = 1_000_000_000


def _auto_fix_money_units(extracted: ExtractedReport) -> tuple[ExtractedReport, Optional[str]]:
    """
    Эвристика: модель иногда неверно выставляет `units_scale` даже при Structured
    Outputs. Например, пишет в `extraction_notes` 'Единицы отчёта — миллиарды
    рублей', но в enum-поле оставляет 'millions'.

    Если в свободном тексте заметок явно упоминается 'млрд' / 'миллиард' и
    units_scale != 'billions' — форсируем billions. Аналогично для 'тыс. руб'.
    """
    notes = (extracted.extraction_notes or "").lower()
    if not notes:
        return extracted, None

    mentions_billions = any(kw in notes for kw in ("млрд", "миллиард", "billion"))
    mentions_thousands = any(kw in notes for kw in ("тыс. руб", "тыс.руб", "тысяч", "thousand"))

    if mentions_billions and extracted.units_scale != "billions":
        fixed = extracted.model_copy(update={"units_scale": "billions"})
        msg = (
            f"AUTO-FIX: в заметках модели упоминаются 'миллиарды', но "
            f"units_scale='{extracted.units_scale}'. Принудительно установлено "
            f"'billions'. Все денежные значения будут × 1000 (в млн)."
        )
        logger.warning(msg)
        return fixed, msg

    if mentions_thousands and extracted.units_scale == "millions":
        # Более консервативно — только если модель сказала 'millions' а пишет
        # про тысячи. Не трогаем, если она уже thousands или units.
        fixed = extracted.model_copy(update={"units_scale": "thousands"})
        msg = (
            f"AUTO-FIX: в заметках модели упоминаются 'тыс. руб.', но "
            f"units_scale='millions'. Принудительно установлено 'thousands'."
        )
        logger.warning(msg)
        return fixed, msg

    return extracted, None


def _auto_fix_shares_units(extracted: ExtractedReport) -> tuple[ExtractedReport, Optional[str]]:
    """
    Эвристика: модель часто не распознаёт подпись единиц у акций
    ('(тыс. штук)' / '(млн. штук)') и возвращает голое число со
    shares_units_scale='units'. Правим по порядку величины и по упоминаниям
    единиц в extraction_notes.

    Логика (ДО rescale_to_millions, числа сырые):
      * scale='units', shares < 10 000              → почти наверняка 'millions'
        (напр. Татнефть '2 103' — в млн. штук = 2.1 млрд)
      * scale='units', 10 000 ≤ shares < 10 000 000 → 'thousands'
        (напр. Русгидро '444 793 377' тыс. = 444 млрд)
      * scale='thousands', shares < 10 000          → 'millions'
        (модель увидела 'млн', но положила в ближайший известный ей 'thousands')
      * extraction_notes содержит 'млн. штук' / 'миллионов акций' → 'millions'

    Плюс подсказки из текста заметок модели (upgrade scale).

    Возвращает (возможно обновлённый report, сообщение для notes или None).
    """
    shares = extracted.shares_outstanding
    if shares is None or shares <= 0:
        return extracted, None

    notes_lc = (extracted.extraction_notes or "").lower()
    mentions_mln_shares = any(
        kw in notes_lc
        for kw in ("млн. штук", "млн штук", "миллион", "млн. акций", "млн акций", "million shares")
    )
    mentions_thousand_shares = any(
        kw in notes_lc
        for kw in ("тыс. штук", "тыс штук", "тысяч акций", "тысяч штук", "thousand shares")
    )

    # 0) САНИТИ: если модель САМА выставила scale='millions', но число слишком
    #    велико для миллионов — это ошибка (она прочитала число в штуках / тыс.).
    #    Реальный диапазон для 'millions': 1..100 000 (Сбер ~22 586 млн штук = 22.6 млрд).
    #    Значение 7_212_635_830 в 'millions' дало бы 7.2×10¹⁵ акций — абсурд.
    if extracted.shares_units_scale == "millions" and shares >= 1_000_000:
        # Откатываем в 'units': если число уже в штуках — после rescale ничего
        # не изменится; если реально было в тыс. — ниже сработает step (4) и
        # переведёт в 'thousands'.
        fixed = extracted.model_copy(update={"shares_units_scale": "units"})
        msg = (
            f"AUTO-FIX: модель указала scale='millions' при shares={shares:,} "
            f"(×10⁶ дало бы {shares * 1_000_000:,} — абсурд для акций). "
            f"Принудительно откат в 'units'. Скорее всего число уже в штуках."
        )
        logger.warning(msg)
        # продолжаем с обновлённым объектом — ниже может сработать ещё одна эвристика
        extracted = fixed
        shares_fix_msg_prefix = msg + " "
    else:
        shares_fix_msg_prefix = ""

    # 1) Модель в заметках явно упомянула 'млн. штук' → принудительно millions,
    #    но ТОЛЬКО если число достаточно маленькое (до 100 000) — иначе это
    #    ошибка модели (она неверно интерпретировала подпись в отчёте).
    if (
        mentions_mln_shares
        and extracted.shares_units_scale != "millions"
        and shares < 1_000_000
    ):
        fixed = extracted.model_copy(update={"shares_units_scale": "millions"})
        msg = (
            f"{shares_fix_msg_prefix}"
            f"AUTO-FIX: в заметках модели упомянуты 'млн. штук', но "
            f"shares_units_scale='{extracted.shares_units_scale}'. Принудительно "
            f"установлено 'millions'. Итоговое число × 1 000 000 = {shares * 1_000_000:,}."
        )
        logger.warning(msg)
        return fixed, msg

    # 2) Модель в заметках явно упомянула 'тыс. штук' → принудительно thousands.
    if (
        mentions_thousand_shares
        and extracted.shares_units_scale == "units"
        and shares < _SUSPICIOUS_SHARES_THRESHOLD * 100  # ограничение на всякий случай
    ):
        fixed = extracted.model_copy(update={"shares_units_scale": "thousands"})
        msg = (
            f"{shares_fix_msg_prefix}"
            f"AUTO-FIX: в заметках модели упомянуты 'тыс. штук', но "
            f"shares_units_scale='units'. Принудительно установлено 'thousands'. "
            f"Итоговое число × 1000 = {shares * 1_000:,}."
        )
        logger.warning(msg)
        return fixed, msg

    # Ниже — эвристики по порядку числа (без подсказок в заметках).

    # 3) Очень маленькое число (<10 000) при scale='units' или 'thousands'
    #    → почти наверняка 'millions'.
    if shares < 10_000 and extracted.shares_units_scale in ("units", "thousands"):
        fixed = extracted.model_copy(update={"shares_units_scale": "millions"})
        msg = (
            f"{shares_fix_msg_prefix}"
            f"AUTO-FIX: shares_outstanding={shares:,} < 10 000 при "
            f"scale='{extracted.shares_units_scale}'. Это почти наверняка "
            f"подпись '(млн. штук)' в отчёте. Принудительно принято "
            f"shares_units_scale='millions', итоговое число × 1 000 000 = "
            f"{shares * 1_000_000:,}. Проверь в отчёте!"
        )
        logger.warning(msg)
        return fixed, msg

    # 4) Число средней величины (10k..10M) при scale='units' → 'thousands'.
    if (
        extracted.shares_units_scale == "units"
        and 10_000 <= shares < _SUSPICIOUS_SHARES_THRESHOLD
    ):
        fixed = extracted.model_copy(update={"shares_units_scale": "thousands"})
        msg = (
            f"{shares_fix_msg_prefix}"
            f"AUTO-FIX: shares_outstanding={shares:,} < 10 млн при scale='units'. "
            f"Это почти наверняка '(тыс. штук)'. Принудительно принято "
            f"shares_units_scale='thousands', итоговое число × 1000 = "
            f"{shares * 1_000:,}. Проверь в отчёте!"
        )
        logger.warning(msg)
        return fixed, msg

    if shares_fix_msg_prefix:
        return extracted, shares_fix_msg_prefix.strip()
    return extracted, None


def _collect_sanity_warnings(extracted: ExtractedReport) -> list[str]:
    """Быстрые sanity-checks поверх извлечённых данных.

    Цель — поймать типичные ошибки модели, которые видно по порядку цифр:
      * не учла тыс. штук в акциях → shares_outstanding слишком маленький;
      * перепутала млрд ↔ млн → revenue/activa микроскопические для крупной компании;
      * нормализация прибыли не сделана (net_income == net_income_reported).
    Предупреждения попадут в extraction_notes и verified_by_analyst=false.
    """
    warnings: list[str] = []

    if extracted.net_income is None:
        warnings.append("net_income не найден — требует ручной проверки")
    if extracted.equity is None:
        warnings.append("equity не найден — требует ручной проверки")

    if extracted.report_type == "bank":
        if extracted.revenue is None:
            warnings.append(
                "revenue (Total Operating Income) не найден — ОБЯЗАТЕЛЬНО проверить"
            )
    else:
        if extracted.current_assets is None or extracted.current_liabilities is None:
            warnings.append(
                "current_assets/current_liabilities не найдены — проверить баланс"
            )

    # Проверка количества акций (после auto-fix и rescale — уже в штуках).
    # Для российских крупных эмитентов на MOEX обычно >= 10 млн акций,
    # а у флагманов (Сбер, Газпром, ВТБ, Русгидро) — миллиарды.
    shares = extracted.shares_outstanding
    if shares is None:
        warnings.append(
            "shares_outstanding не найден — бери 'Средневзвешенное количество "
            "обыкновенных акций' из примечаний к EPS"
        )
    elif shares < _SUSPICIOUS_SHARES_THRESHOLD:
        # Auto-fix не сработал (shares_units_scale уже был 'thousands' и всё
        # равно получилось < 10 млн) — редкий случай, но всё равно пометим.
        warnings.append(
            f"shares_outstanding={shares:,} — ПОДОЗРИТЕЛЬНО МАЛО даже после "
            f"нормализации единиц. Проверь отчёт вручную."
        )
    elif shares < _SHARES_SOFT_WARN_THRESHOLD:
        # Мягкий уровень: 10M..1B — для мелких/средних эмитентов это норма
        # (например Транснефть-п: ~1.5M), но для флагманов типа Русгидро или
        # Сбера это явно 3 «потерянных» нуля. Автоисправление опасно из-за
        # false-positive, поэтому просим аналитика сверить с MOEX.
        warnings.append(
            f"shares_outstanding={shares:,} — между 10 млн и 1 млрд. "
            f"Для крупных эмитентов (Сбер, Газпром, Русгидро и т.п.) это "
            f"подозрительно мало: скорее всего AI не учёл '(тыс. штук)' в "
            f"отчёте. ОБЯЗАТЕЛЬНО сверь с актуальным реестром MOEX "
            f"(в форме редактирования — кнопка «↺ MOEX»)."
        )

    # Проверка порядка цифр. Для годового отчёта крупной публичной компании
    # revenue < 1000 млн руб (< 1 млрд) — крайне маловероятно.
    revenue_mln = extracted.revenue
    if revenue_mln is not None and 0 < revenue_mln < 1_000:
        warnings.append(
            f"revenue={revenue_mln:.2f} млн — ПОДОЗРИТЕЛЬНО МАЛО для годового "
            f"отчёта крупной компании. Возможно, в шапке было 'млрд руб.', "
            f"а units_scale определён как 'millions'. Проверь!"
        )

    total_assets_mln = extracted.total_assets
    if total_assets_mln is not None and 0 < total_assets_mln < 1_000:
        warnings.append(
            f"total_assets={total_assets_mln:.2f} млн — ПОДОЗРИТЕЛЬНО МАЛО. "
            f"Проверь единицы (млн vs млрд) в шапке баланса."
        )

    # Согласованность единиц между полями. Типичная ошибка gpt-4o-mini на
    # сжатых отчётах (Роснефть): часть полей в млрд, часть в млн.
    # Проверки инвариантов:
    #   * net_income не может быть больше revenue (прибыль всегда ≤ выручки);
    #   * total_assets обычно в 1..10 раз больше revenue (не 1/100).
    if revenue_mln and extracted.net_income is not None:
        if abs(extracted.net_income) > abs(revenue_mln) * 2 and abs(revenue_mln) > 0:
            warnings.append(
                f"net_income={extracted.net_income:.0f} млн > 2×revenue="
                f"{revenue_mln:.0f} млн — ИНВАРИАНТ НАРУШЕН. Почти наверняка "
                f"разные поля извлечены в разных единицах (часть в млрд, часть "
                f"в млн). Проверь вручную."
            )
    if revenue_mln and total_assets_mln is not None:
        if abs(revenue_mln) > 0 and abs(total_assets_mln) / abs(revenue_mln) > 1000:
            warnings.append(
                f"total_assets / revenue = {total_assets_mln/revenue_mln:.0f} — "
                f"ПОДОЗРИТЕЛЬНОЕ соотношение. Вероятно, разные единицы."
            )
        if abs(total_assets_mln) > 0 and abs(revenue_mln) / abs(total_assets_mln) > 1000:
            warnings.append(
                f"revenue / total_assets = {revenue_mln/total_assets_mln:.0f} — "
                f"ПОДОЗРИТЕЛЬНОЕ соотношение. Вероятно, разные единицы."
            )

    # Нормализация прибыли.
    # Если net_income == net_income_reported и нет явного упоминания в заметках
    # модели, что было сделано — значит нормализация не сработала, аналитику нужно
    # посчитать самому.
    ni = extracted.net_income
    nir = extracted.net_income_reported
    if ni is not None and nir is not None and abs(ni - nir) < 0.01:
        model_notes_lc = (extracted.extraction_notes or "").lower()
        normalized_mentioned = any(
            kw in model_notes_lc
            for kw in ("нормализован", "normalize", "adjust", "исключ", "разов")
        )
        if not normalized_mentioned:
            warnings.append(
                "net_income == net_income_reported (нормализация, вероятно, НЕ сделана). "
                "По Грэму: из прибыли до налога исключить крупные разовые элементы "
                "(> 10% в совокупности) и применить ставку 20% (× 0.8). "
                "Это должен сделать финансовый аналитик."
            )

    # Дивиденды.
    if extracted.dividends_per_share is None and extracted.dividends_paid:
        warnings.append(
            "dividends_paid=true, но dividends_per_share=null. "
            "Возможно, финальные дивиденды за год ещё не объявлены (они будут "
            "в отчёте за следующий год). Проверь вручную."
        )

    return warnings


def _build_extraction_notes(
    extracted: ExtractedReport,
    pdf_label: str,
    selected_pages: int,
    total_pages: int,
    extra_warnings: Optional[list[Optional[str]]] = None,
) -> str:
    """Собрать финальный extraction_notes с техническими метаданными + заметки модели."""
    header = (
        f"[AUTO-EXTRACTED | model={settings.extraction_model_label} | "
        f"pdf={pdf_label} | pages_used={selected_pages}/{total_pages} | "
        f"scale_in_pdf={extracted.units_scale} | "
        f"shares_scale_in_pdf={extracted.shares_units_scale} | "
        f"confidence={extracted.confidence or 'n/a'}]"
    )
    model_notes = (extracted.extraction_notes or "").strip()
    warnings = _collect_sanity_warnings(extracted)
    for w in extra_warnings or []:
        if w:
            warnings.insert(0, w)  # автокоррекции — в начало списка

    parts = [header]
    if model_notes:
        parts.append("Заметки модели:\n" + model_notes)
    if warnings:
        parts.append("Флаги для проверки:\n- " + "\n- ".join(warnings))

    return "\n\n".join(parts)


def _find_existing_report(
    db: Session,
    *,
    company_id: int,
    fiscal_year: int,
    fiscal_quarter: Optional[int],
    period_type: str,
    accounting_standard: str,
    consolidated: bool,
) -> Optional[FinancialReport]:
    q = (
        db.query(FinancialReport)
        .filter(FinancialReport.company_id == company_id)
        .filter(FinancialReport.fiscal_year == fiscal_year)
        .filter(FinancialReport.period_type == period_type)
        .filter(FinancialReport.accounting_standard == accounting_standard)
        .filter(FinancialReport.consolidated.is_(consolidated))
    )
    if fiscal_quarter is None:
        q = q.filter(FinancialReport.fiscal_quarter.is_(None))
    else:
        q = q.filter(FinancialReport.fiscal_quarter == fiscal_quarter)
    return q.first()


# ─── Основной пайплайн для одного PDF ────────────────────────────────────────


def parse_pdf_to_report(
    db: Session,
    *,
    pdf_source: Union[Path, bytes],
    company: Company,
    fiscal_year: int,
    dry_run: bool = False,
    force: bool = False,
    period_type: str = "annual",
    fiscal_quarter: Optional[int] = None,
    accounting_standard: str = "IFRS",
    consolidated: bool = True,
    source_pdf_path: Optional[str] = None,
    pdf_label: Optional[str] = None,
) -> ExtractionOutcome:
    """
    Прогнать PDF через AI-пайплайн и (при dry_run=False) создать FinancialReport
    с auto_extracted=True и verified_by_analyst=False.

    Args:
        db: открытая сессия SQLAlchemy.
        pdf_source: либо путь к PDF, либо байты (например, из UploadFile).
        company: ORM-объект Company (должен существовать в БД).
        fiscal_year: ожидаемый год отчёта.
        dry_run: если True — только показать результат, не писать в БД.
        force: если True — удалить существующий отчёт и создать заново.
        period_type/fiscal_quarter/accounting_standard/consolidated — атрибуты,
            определяющие уникальный ключ отчёта.
        source_pdf_path: что записать в `financial_reports.source_pdf_path`.
        pdf_label: человекочитаемое имя PDF для логов и заметок (если передали bytes).

    Raises:
        ReportAlreadyExistsError: если отчёт уже есть и force=False.
        LLMNotConfiguredError: если не настроен LLM.
        LLMParseError: если LLM вернул невалидные данные.
        RuntimeError: если PDF не содержит финансовых таблиц.
        ValueError: если fiscal_year находится в будущем.
    """
    # Guard: защита от случайно введённого «будущего» года.
    # Публичная компания не может выпустить годовой отчёт за ещё не
    # завершившийся год. Допускаем только текущий календарный (может быть
    # preliminary-отчёт) и всё, что раньше.
    current_year = date.today().year
    if fiscal_year > current_year:
        raise ValueError(
            f"fiscal_year={fiscal_year} находится в будущем "
            f"(текущий год — {current_year}). Годовой отчёт не может быть "
            f"опубликован за ещё не завершившийся год. Проверь поле "
            f"«Отчётный год» в форме загрузки."
        )

    resolved_report_type = sector_to_report_type(company.sector)

    if isinstance(pdf_source, Path):
        label = pdf_label or pdf_source.name
        if not source_pdf_path:
            source_pdf_path = str(pdf_source)
    else:
        label = pdf_label or "uploaded.pdf"

    outcome = ExtractionOutcome(
        ticker=company.ticker,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        report_type=resolved_report_type,
        dry_run=dry_run,
        pdf_label=label,
    )

    # 1) Дубликат?
    existing = _find_existing_report(
        db,
        company_id=company.id,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_type=period_type,
        accounting_standard=accounting_standard,
        consolidated=consolidated,
    )
    if existing and not force:
        raise ReportAlreadyExistsError(existing.id)  # type: ignore[arg-type]

    # 2) Выбор релевантных страниц PDF
    extraction: PdfExtractionResult = extract_financial_pages(
        pdf_source, pdf_label=label
    )
    outcome.selected_pages = len(extraction.selected_pages)
    outcome.total_pages = extraction.total_pages

    # 3) Промпты
    system_prompt = build_system_prompt(resolved_report_type)
    user_prompt = build_user_prompt(
        ticker=company.ticker,  # type: ignore[arg-type]
        expected_year=fiscal_year,
        company_name=company.name,  # type: ignore[arg-type]
        sector=company.sector,  # type: ignore[arg-type]
        pdf_text=extraction.text,
        is_scanned=extraction.is_scanned,
    )

    # 4) Вызов LLM (исключения LLMNotConfiguredError/LLMParseError/LLMTransientError
    #    поднимутся наружу — их ловит вызывающий код).
    #    Для скан-PDF передаём страницы как PNG — vision-модель прочитает их
    #    напрямую (tesseract не нужен).
    extracted = extract_report_via_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        images=extraction.page_images if extraction.is_scanned else None,
    )
    if extraction.is_scanned:
        logger.info(
            "[%s %s] PDF обработан в vision-режиме: отправлено %d страниц-PNG.",
            company.ticker, fiscal_year, len(extraction.page_images),
        )

    # 5) Auto-fix units ДО rescale (пока числа ещё «сырые»).
    # Сначала деньги (млрд ↔ млн), затем акции — порядок важен, т.к. акции
    # не зависят от money scale, но лишняя инвариантность удобна.
    extracted, money_autofix_msg = _auto_fix_money_units(extracted)
    extracted, shares_autofix_msg = _auto_fix_shares_units(extracted)

    # 5.1) Конвертация единиц в миллионы / акций в штуки
    extracted = rescale_to_millions(extracted)

    # 5.2) Санити-чек: совпадает ли fiscal_year
    if extracted.fiscal_year != fiscal_year:
        logger.warning(
            "[%s %s] LLM вернул fiscal_year=%d, ожидали %d. Форсируем ожидаемый.",
            company.ticker, fiscal_year, extracted.fiscal_year, fiscal_year,
        )
        extracted = extracted.model_copy(update={"fiscal_year": fiscal_year})

    outcome.extracted = extracted

    # 6) Соберём extraction_notes
    notes = _build_extraction_notes(
        extracted=extracted,
        pdf_label=label,
        selected_pages=len(extraction.selected_pages),
        total_pages=extraction.total_pages,
        extra_warnings=[money_autofix_msg, shares_autofix_msg],
    )

    # 7) Для банка NULL'им current_assets/current_liabilities.
    ca = extracted.current_assets
    cl = extracted.current_liabilities
    if resolved_report_type == "bank":
        ca = None
        cl = None

    # 7.1) Для отчётов в иностранной валюте подтягиваем курс к рублю на дату
    # окончания отчётного периода. Делается ДО подтяжки цен, т.к. при USD/EUR
    # отчёте цену MOEX (в рублях) нужно будет разделить на курс, чтобы сохранить
    # инвариант «все денежные поля в валюте отчёта».
    #
    # Источники: MOEX (биржевой, 2012..июнь-2024) → CBR (официальный, fallback).
    auto_exchange_rate: Optional[float] = None
    if extracted.currency and extracted.currency.upper() != "RUB":
        report_iso = _resolve_report_date(extracted)
        report_d = _parse_iso_date(report_iso)
        auto_exchange_rate = _fetch_fx_rate_for_report(extracted.currency, report_d)
        if auto_exchange_rate is not None:
            logger.info(
                "[%s %s] Курс %s/RUB автоматически подтянут на %s: %.4f.",
                company.ticker, fiscal_year,
                extracted.currency, report_d, auto_exchange_rate,
            )
        else:
            # Pydantic-валидатор FinancialReportCreate всё равно упал бы при
            # попытке сохранить отчёт в иностранной валюте без exchange_rate.
            # Бросаем ValueError — роутер маппит его в HTTP 400 с понятным
            # сообщением, UI покажет его корректно (а не под маской 502 «LLM
            # вернул некорректный JSON», что вводило бы в заблуждение).
            raise ValueError(
                f"Отчёт извлечён в валюте {extracted.currency}, но курс "
                f"{extracted.currency}/RUB на дату {report_d or 'не определена'} "
                f"не удалось получить ни с MOEX, ни с ЦБ РФ. "
                f"Проверьте report_date или внесите отчёт вручную, указав "
                f"exchange_rate в форме."
            )

    # 7.2) Подтягиваем рыночные цены с MOEX (best-effort). Для non-RUB отчётов
    # цена конвертируется в валюту отчёта (делением на auto_exchange_rate),
    # чтобы сохранить инвариант проекта: все денежные поля — в `currency`,
    # а `calc_multipliers` умножает на exchange_rate при расчёте P/E и P/B.
    moex_price_on_report, moex_price_on_filing = _enrich_with_moex_prices(
        extracted,
        ticker=company.ticker,  # type: ignore[arg-type]
        exchange_rate=auto_exchange_rate,
    )
    if moex_price_on_report is not None or moex_price_on_filing is not None:
        logger.info(
            "[%s %s] MOEX prices подтянуты автоматически (валюта отчёта %s): "
            "на report_date=%s, на filing_date=%s.",
            company.ticker, fiscal_year, extracted.currency,
            moex_price_on_report, moex_price_on_filing,
        )

    payload = FinancialReportCreate(
        company_id=company.id,  # type: ignore[arg-type]
        period_type=period_type,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        accounting_standard=accounting_standard,  # type: ignore[arg-type]
        consolidated=consolidated,
        source="company_website",  # type: ignore[arg-type]
        report_date=_resolve_report_date(extracted),
        filing_date=extracted.filing_date,
        price_per_share=moex_price_on_report,
        price_at_filing=moex_price_on_filing,
        shares_outstanding=extracted.shares_outstanding,
        revenue=extracted.revenue,
        net_income=extracted.net_income,
        net_income_reported=extracted.net_income_reported,
        total_assets=extracted.total_assets,
        current_assets=ca,
        total_liabilities=extracted.total_liabilities,
        current_liabilities=cl,
        equity=extracted.equity,
        dividends_per_share=extracted.dividends_per_share,
        dividends_paid=extracted.dividends_paid,
        net_interest_income=extracted.net_interest_income,
        fee_commission_income=extracted.fee_commission_income,
        operating_expenses=extracted.operating_expenses,
        provisions=extracted.provisions,
        currency=extracted.currency,
        exchange_rate=auto_exchange_rate,
        auto_extracted=True,
        verified_by_analyst=False,
        extraction_notes=notes,
        extraction_model=settings.extraction_model_label,
        source_pdf_path=source_pdf_path,
    )

    if dry_run:
        logger.info(
            "[DRY-RUN %s %s] revenue=%s net_income=%s equity=%s assets=%s "
            "liabilities=%s report_type=%s currency=%s",
            company.ticker, fiscal_year,
            extracted.revenue, extracted.net_income, extracted.equity,
            extracted.total_assets, extracted.total_liabilities,
            resolved_report_type, extracted.currency,
        )
        return outcome

    # 8) Запись в БД.
    #
    # При force=True мы НЕ удаляем существующую запись и не создаём новую —
    # это бы поменяло id отчёта и оборвало ссылки из `multipliers`
    # (FK с ON DELETE SET NULL обнулит `report_id` у всех исторических
    # мультипликаторов). Вместо этого делаем UPDATE по месту: id сохраняется,
    # мультипликаторы (upsert по (company_id, date, type)) плавно
    # переcчитываются, URL/закладки продолжают работать.
    if existing and force:
        logger.warning(
            "[%s %s] Обновляем существующий отчёт (id=%d, force=True).",
            company.ticker, fiscal_year, existing.id,
        )
        created = report_service.update_report(
            db=db, report_id=existing.id, report_data=payload,  # type: ignore[arg-type]
        )
        if created is None:
            # Существующий внезапно исчез между find_existing и update — крайне
            # редкий случай (параллельное удаление). Фолбэком создаём заново.
            created = report_service.create_report(db=db, report_data=payload)
        else:
            # update_report не трогает технические AI-поля (они заданы как
            # write-once и меняются только через явный апдейт здесь).
            created.auto_extracted = True  # type: ignore[assignment]
            created.extraction_model = settings.extraction_model_label  # type: ignore[assignment]
            if source_pdf_path is not None:
                created.source_pdf_path = source_pdf_path  # type: ignore[assignment]
            db.commit()
            db.refresh(created)
    else:
        created = report_service.create_report(db=db, report_data=payload)

    outcome.created_report_id = created.id  # type: ignore[assignment]
    logger.info(
        "[%s %s] %s отчёт id=%s (auto_extracted=True, verified=False).",
        company.ticker, fiscal_year,
        "Обновлён" if (existing and force) else "Создан",
        created.id,
    )
    return outcome


# ─── Режим сравнения с уже существующим отчётом ─────────────────────────────


def _normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value[:10]  # берём только YYYY-MM-DD
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10]
    return str(value)[:10]


def _to_float(value: Any) -> Optional[float]:
    """Привести значение из БД (Decimal / int / float) к float, либо None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_money_status(
    existing_raw: Any, extracted_raw: Any
) -> tuple[Status, Optional[float], Optional[float], Optional[str]]:
    """Статус для денежного поля (в миллионах). Возвращает (status, abs, pct, note)."""
    existing = _to_float(existing_raw)
    extracted = _to_float(extracted_raw)
    if existing is None and extracted is None:
        return "both_missing", None, None, None
    if existing is None and extracted is not None:
        return "missing_existing", None, None, "Аналитик не заполнил — модель предложила значение"
    if existing is not None and extracted is None:
        return "missing_ai", None, None, "Модель НЕ извлекла значение — требует внимания"

    assert existing is not None and extracted is not None
    abs_d = abs(existing - extracted)
    base = abs(existing) if existing != 0 else max(abs(extracted), 1.0)
    pct = (extracted - existing) / base * 100.0

    if abs_d < _MATERIAL_MONEY_THRESHOLD_MLN and abs(pct) < _MATERIAL_PCT_THRESHOLD:
        return "match", abs_d, pct, None
    if abs(pct) < 1.0:
        return "close", abs_d, pct, "Разница < 1% (округление / переоценка)"
    return "mismatch", abs_d, pct, None


def _compute_generic_status(
    existing: Any, extracted: Any, kind: str
) -> tuple[Status, Optional[float], Optional[float], Optional[str]]:
    """Статус для нечисловых / небольших числовых полей."""
    if kind == "date":
        e = _normalize_date(existing)
        x = _normalize_date(extracted)
        if e is None and x is None:
            return "both_missing", None, None, None
        if e is None:
            return "missing_existing", None, None, None
        if x is None:
            return "missing_ai", None, None, None
        return ("match" if e == x else "mismatch"), None, None, None

    if kind == "bool":
        e = None if existing is None else bool(existing)
        x = None if extracted is None else bool(extracted)
        if e is None and x is None:
            return "both_missing", None, None, None
        if e is None:
            return "missing_existing", None, None, None
        if x is None:
            return "missing_ai", None, None, None
        return ("match" if e == x else "mismatch"), None, None, None

    if kind == "str":
        e = (existing or "").strip() if isinstance(existing, str) else existing
        x = (extracted or "").strip() if isinstance(extracted, str) else extracted
        if e is None and x is None:
            return "both_missing", None, None, None
        if e is None:
            return "missing_existing", None, None, None
        if x is None:
            return "missing_ai", None, None, None
        return ("match" if str(e).upper() == str(x).upper() else "mismatch"), None, None, None

    # int / float (не деньги) — считаем как деньги, но без единиц
    e_f = _to_float(existing)
    x_f = _to_float(extracted)
    if e_f is None and x_f is None:
        return "both_missing", None, None, None
    if e_f is None:
        return "missing_existing", None, None, None
    if x_f is None:
        return "missing_ai", None, None, None

    abs_d = abs(e_f - x_f)
    base = abs(e_f) if e_f != 0 else max(abs(x_f), 1.0)
    pct = (x_f - e_f) / base * 100.0
    if abs_d < 1e-6 or abs(pct) < _MATERIAL_PCT_THRESHOLD:
        return "match", abs_d, pct, None
    if abs(pct) < 1.0:
        return "close", abs_d, pct, None
    return "mismatch", abs_d, pct, None


def compute_report_diff(
    existing: FinancialReport,
    extracted: ExtractedReport,
    *,
    report_type: str,
) -> tuple[list[ReportFieldDiff], ComparisonSummary]:
    """
    Поле за полем сравнить существующий (ручной) отчёт с AI-извлечением.

    Только поля, имеющие смысл для данного `report_type` (general / bank).
    """
    diffs: list[ReportFieldDiff] = []
    summary = ComparisonSummary()
    max_pct: Optional[float] = None

    for spec in _COMPARABLE_FIELDS:
        if report_type not in spec.relevant_for:
            continue

        existing_raw = getattr(existing, spec.key, None)
        extracted_raw = getattr(extracted, spec.key, None)

        if spec.kind == "money_mln":
            status, abs_d, pct, note = _compute_money_status(
                existing_raw, extracted_raw
            )
        else:
            status, abs_d, pct, note = _compute_generic_status(
                existing_raw, extracted_raw, spec.kind
            )

        diffs.append(
            ReportFieldDiff(
                field=spec.key,
                label=spec.label,
                kind=spec.kind,
                existing_value=existing_raw,
                extracted_value=extracted_raw,
                abs_diff=abs_d,
                pct_diff=pct,
                status=status,
                note=note,
            )
        )

        summary.total_fields += 1
        if status == "match":
            summary.matched += 1
        elif status == "close":
            summary.close += 1
        elif status == "mismatch":
            summary.mismatched += 1
        elif status == "missing_ai":
            summary.missing_in_ai += 1
        elif status == "missing_existing":
            summary.missing_in_existing += 1
        elif status == "both_missing":
            summary.both_missing += 1

        if pct is not None:
            if max_pct is None or abs(pct) > abs(max_pct):
                max_pct = pct

    summary.max_pct_diff = max_pct
    return diffs, summary


def compare_pdf_with_existing(
    db: Session,
    *,
    pdf_source: Union[Path, bytes],
    company: Company,
    fiscal_year: int,
    period_type: str = "annual",
    fiscal_quarter: Optional[int] = None,
    accounting_standard: str = "IFRS",
    consolidated: bool = True,
    pdf_label: Optional[str] = None,
) -> ComparisonResult:
    """
    Прогнать PDF через LLM и сравнить с уже существующим отчётом в БД
    БЕЗ каких-либо изменений в БД. Полезно для оценки качества модели
    на уже подтверждённых аналитиком отчётах.

    Raises:
        ReportNotFoundForComparison: если отчёта для сравнения ещё нет.
        LLMNotConfiguredError / LLMParseError / LLMTransientError: см. parse_pdf_to_report.
        RuntimeError: если PDF не содержит финансовых таблиц.
    """
    resolved_report_type = sector_to_report_type(company.sector)

    if isinstance(pdf_source, Path):
        label = pdf_label or pdf_source.name
    else:
        label = pdf_label or "uploaded.pdf"

    existing = _find_existing_report(
        db,
        company_id=company.id,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        period_type=period_type,
        accounting_standard=accounting_standard,
        consolidated=consolidated,
    )
    if not existing:
        raise ReportNotFoundForComparison(
            f"В БД нет отчёта {company.ticker} {fiscal_year} ({period_type}, "
            f"{accounting_standard}) для сравнения. Используйте обычный upload."
        )

    extraction: PdfExtractionResult = extract_financial_pages(pdf_source, pdf_label=label)

    system_prompt = build_system_prompt(resolved_report_type)
    user_prompt = build_user_prompt(
        ticker=company.ticker,  # type: ignore[arg-type]
        expected_year=fiscal_year,
        company_name=company.name,  # type: ignore[arg-type]
        sector=company.sector,  # type: ignore[arg-type]
        pdf_text=extraction.text,
        is_scanned=extraction.is_scanned,
    )

    extracted = extract_report_via_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        images=extraction.page_images if extraction.is_scanned else None,
    )
    if extraction.is_scanned:
        logger.info(
            "[COMPARE %s %s] PDF в vision-режиме: %d страниц-PNG.",
            company.ticker, fiscal_year, len(extraction.page_images),
        )
    extracted, money_autofix_msg = _auto_fix_money_units(extracted)
    extracted, shares_autofix_msg = _auto_fix_shares_units(extracted)
    extracted = rescale_to_millions(extracted)
    if extracted.fiscal_year != fiscal_year:
        extracted = extracted.model_copy(update={"fiscal_year": fiscal_year})

    # Обогатим extraction_notes тем же списком sanity-предупреждений, что
    # используется в parse_pdf_to_report — чтобы аналитик видел красные флаги
    # прямо в compare-режиме.
    enriched_notes = _build_extraction_notes(
        extracted=extracted,
        pdf_label=label,
        selected_pages=len(extraction.selected_pages),
        total_pages=extraction.total_pages,
        extra_warnings=[money_autofix_msg, shares_autofix_msg],
    )
    extracted = extracted.model_copy(update={"extraction_notes": enriched_notes})

    diffs, summary = compute_report_diff(
        existing, extracted, report_type=resolved_report_type
    )

    logger.info(
        "[COMPARE %s %s] existing_id=%s matched=%d/%d mismatched=%d missing_ai=%d max_pct=%s",
        company.ticker, fiscal_year, existing.id,
        summary.matched, summary.total_fields, summary.mismatched,
        summary.missing_in_ai,
        f"{summary.max_pct_diff:+.2f}%" if summary.max_pct_diff is not None else "n/a",
    )

    return ComparisonResult(
        ticker=company.ticker,  # type: ignore[arg-type]
        fiscal_year=fiscal_year,
        report_type=resolved_report_type,
        existing_report_id=existing.id,  # type: ignore[arg-type]
        existing_report_verified=bool(existing.verified_by_analyst),
        extracted=extracted,
        diffs=diffs,
        summary=summary,
        pdf_label=label,
        selected_pages=len(extraction.selected_pages),
        total_pages=extraction.total_pages,
    )


class ReportNotFoundForComparison(RuntimeError):
    """Нет существующего отчёта в БД — с чем сравнивать нечего."""


__all__ = (
    "ComparisonResult",
    "ComparisonSummary",
    "ExtractionOutcome",
    "LLMNotConfiguredError",
    "LLMParseError",
    "LLMTransientError",
    "ReportAlreadyExistsError",
    "ReportFieldDiff",
    "ReportNotFoundForComparison",
    "compare_pdf_with_existing",
    "compute_report_diff",
    "parse_pdf_to_report",
)
