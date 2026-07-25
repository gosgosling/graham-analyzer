"""Извлечение релевантных страниц из PDF финансового отчёта.

Цель — НЕ отдавать в LLM весь отчёт (150-300 страниц), а выделить только
страницы с ключевыми финансовыми таблицами:
  - Консолидированный отчёт о финансовом положении / Баланс
  - Отчёт о прибылях и убытках / Отчёт о совокупном доходе
  - Основные сведения для банков (Чистые процентные доходы, резервы)
  - Сведения о дивидендах и капитале
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Union

import pymupdf  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


SECTION_KEYWORDS: tuple[tuple[str, ...], ...] = (
    (
        "консолидированный отчет о финансовом положении",
        "отчет о финансовом положении",
        "консолидированный баланс",
        "бухгалтерский баланс",
        "statement of financial position",
        "consolidated statement of financial position",
        "balance sheet",
    ),
    (
        "консолидированный отчет о прибылях и убытках",
        "отчет о прибылях и убытках",
        "отчет о прибыли или убытке",
        "отчет о совокупном доходе",
        "отчет о совокупной прибыли",
        "statement of profit or loss",
        "statement of comprehensive income",
        "income statement",
    ),
    (
        "чистые процентные доходы",
        "процентные доходы",
        "резерв под обесценение",
        "резерв под ожидаемые кредитные убытки",
        "operating income of the bank",
        "net interest income",
    ),
    (
        "отчет об изменениях в капитале",
        "дивиденды",
        "прибыль на акцию",
        "statement of changes in equity",
        "earnings per share",
        "dividends declared",
    ),
    # Отчёт о движении денежных средств (ОДДС) — нужен для OCF, CAPEX, аренды.
    (
        "отчет о движении денежных средств",
        "консолидированный отчет о движении денежных средств",
        "движение денежных средств",
        "денежные потоки от операционной деятельности",
        "денежные средства от операционной деятельности",
        "операционная деятельность",
        "инвестиционная деятельность",
        "финансовая деятельность",
        "приобретение основных средств",
        "погашение обязательств по аренде",
        "statement of cash flows",
        "cash flows from operating activities",
        "net cash from operating activities",
        "purchase of property, plant and equipment",
        "payment of lease liabilities",
        "погашение кредитов и займов",
        "repayment of borrowings",
    ),
    # Амортизация: нужна для сравнения с CAPEX и расчёта owner earnings.
    # Чаще всего живёт в корректировках ОДДС, но у части эмитентов — только
    # в примечании о себестоимости или об основных средствах.
    (
        "износ и амортизация",
        "амортизация основных средств",
        "амортизация нематериальных активов",
        "амортизация права пользования",
        "расходы на амортизацию",
        "depreciation and amortisation",
        "depreciation and amortization",
        "depreciation, depletion and amortisation",
        "depreciation of right-of-use assets",
    ),
    # Примечание о дивидендах: только там пишут, что выплата разовая —
    # «специальный дивиденд», «доплата за прошлый год».
    (
        "специальный дивиденд",
        "специальные дивиденды",
        "дивиденды на акцию",
        "объявленные дивиденды",
        "дивиденды объявлены",
        "special dividend",
        "dividend per share",
        "dividends per ordinary share",
    ),
    # Строки долга и денег в балансе — чтобы страница с ними точно попала.
    (
        "кредиты и займы",
        "краткосрочные кредиты и займы",
        "долгосрочные кредиты и займы",
        "заемные средства",
        "денежные средства и их эквиваленты",
        "loans and borrowings",
        "cash and cash equivalents",
    ),
    # Итоговые строки баланса — страницы, где они есть, ВСЕГДА должны попадать
    # в извлечённый текст (именно на них LLM должен искать current_*).
    (
        "итого активы",
        "итого активов",
        "всего активы",
        "итого обязательства",
        "итого обязательств",
        "всего обязательств",
        "итого капитал",
        "итого капитала",
        "итого оборотные активы",
        "итого оборотных активов",
        "итого текущие активы",
        "итого текущих активов",
        "итого краткосрочные обязательства",
        "итого краткосрочных обязательств",
        "итого текущие обязательства",
        "итого текущих обязательств",
        "итого долгосрочные обязательства",
        "итого долгосрочных обязательств",
        "total current assets",
        "total current liabilities",
        "total non-current assets",
        "total non-current liabilities",
        "total assets",
        "total liabilities",
    ),
)


@dataclass
class PdfExtractionResult:
    """Результат выбора релевантных страниц."""
    pdf_path: Path
    total_pages: int
    selected_pages: list[int]  # 0-индексированные
    text: str                  # склеенный текст выбранных страниц
    matched_sections: dict[int, list[str]]
    is_scanned: bool = False   # True если PDF — скан (почти нет извлекаемого текста)
    page_images: list[bytes] = None  # type: ignore[assignment]  # PNG-страниц для vision LLM

    def __post_init__(self) -> None:
        if self.page_images is None:
            self.page_images = []


def _normalize(text: str) -> str:
    """Нормализация для сравнения: нижний регистр, ё→е, единый пробел."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def _find_matches(page_text_norm: str) -> tuple[list[str], dict[int, int]]:
    """
    Совпадения ключевых фраз на странице.

    Возвращает список найденных фраз и число попаданий по каждой тематической
    группе — по группам потом распределяется квота страниц, чтобы при
    переполнении не потерять целый раздел.
    """
    matches: list[str] = []
    hits_by_group: dict[int, int] = {}
    for group_index, group in enumerate(SECTION_KEYWORDS):
        for phrase in group:
            if phrase in page_text_norm:
                matches.append(phrase)
                hits_by_group[group_index] = hits_by_group.get(group_index, 0) + 1
    return matches, hits_by_group


def _prioritized_pages(
    matched_sections: dict[int, list[str]],
    hits_by_page: dict[int, dict[int, int]],
    limit: int,
) -> list[int]:
    """
    Отобрать страницы при переполнении лимита.

    Сначала берём по одной лучшей странице на каждую тематическую группу:
    иначе сортировка по общему числу совпадений всегда выигрывает в пользу
    баланса (там десятки строк «Итого …»), и страница с амортизацией или
    примечанием о дивидендах вылетает из контекста именно на толстых отчётах.
    Остаток квоты добираем по общему числу совпадений.
    """
    chosen: list[int] = []
    used: set[int] = set()

    for group_index in range(len(SECTION_KEYWORDS)):
        candidates = [
            (hits.get(group_index, 0), page)
            for page, hits in hits_by_page.items()
            if hits.get(group_index)
        ]
        if not candidates:
            continue
        _, page = max(candidates)
        if page not in used:
            used.add(page)
            chosen.append(page)
        if len(chosen) >= limit:
            return chosen

    for page, phrases in sorted(
        matched_sections.items(), key=lambda kv: len(kv[1]), reverse=True
    ):
        if page in used:
            continue
        used.add(page)
        chosen.append(page)
        if len(chosen) >= limit:
            break

    return chosen


def _expand_neighbors(indices: Iterable[int], total: int, window: int = 1) -> list[int]:
    selected: set[int] = set()
    for i in indices:
        for j in range(i - window, i + window + 1):
            if 0 <= j < total:
                selected.add(j)
    return sorted(selected)


# Порог в символах на странице, ниже которого страница считается сканом
# (или таблицей, сохранённой в виде картинки в PDF).
_SCAN_PAGE_TEXT_THRESHOLD = 100

# Максимум страниц, которые мы можем отправить как PNG в vision-LLM.
# С detail="high" каждая страница съедает ~700-1700 токенов, плюс сам
# текстовый промпт. 10 страниц = ~15-20K токенов, что безопасно
# укладывается в TPM-лимит (200K/min на OpenAI Tier 1) при
# параллельных запросах.
_MAX_SCAN_PAGES_FOR_VISION = 10

# DPI для рендеринга страниц в PNG. 150 даёт хороший баланс читаемости /
# размера (типичная A4 ≈ 300 КБ PNG).
_RENDER_DPI = 150


def _render_page_png(page: "pymupdf.Page", dpi: int = _RENDER_DPI) -> bytes:
    """Отрендерить одну страницу PDF в PNG-байты для vision-модели."""
    scale = dpi / 72.0
    matrix = pymupdf.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("png")


def _looks_like_scan(page_texts: list[str]) -> bool:
    """Эвристика: большая часть страниц почти не содержит извлекаемого текста
    → PDF либо целиком скан, либо важные таблицы в нём — растровые картинки."""
    if not page_texts:
        return False
    non_empty = sum(1 for t in page_texts if len(t.strip()) >= _SCAN_PAGE_TEXT_THRESHOLD)
    return non_empty < max(1, len(page_texts) * 0.3)


def _cyrillic_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 80:
        return 1.0  # мало букв — не считаем «битой» кодировкой
    cyr = sum(1 for ch in letters if ("А" <= ch <= "я") or ch in "Ёё")
    return cyr / len(letters)


def _looks_like_garbled_encoding(page_texts: list[str]) -> bool:
    """Текст есть, но почти без кириллицы (битый ToUnicode, как у ALRS 2024/2025).

    Ключевые фразы не матчятся → без vision прогон падает. Считаем такие PDF
    «сканами» и отдаём PNG vision-модели.
    """
    sample = "\n".join(page_texts[: min(20, len(page_texts))])
    if len(sample.strip()) < 500:
        return False
    return _cyrillic_ratio(sample) < 0.15


def extract_financial_pages(
    pdf_source: Union[Path, bytes],
    neighbor_window: int = 2,
    max_pages: int = 60,
    *,
    pdf_label: str = "in-memory PDF",
) -> PdfExtractionResult:
    """
    Прочитать PDF (из файла или bytes), выбрать страницы с финансовыми таблицами.

    Работает в двух режимах:
      1. Текстовый PDF — ищем релевантные страницы по ключевым фразам,
         возвращаем их склеенный текст.
      2. Скан-PDF — ключевые фразы не ищутся (текста почти нет); рендерим
         разумное количество страниц в PNG и отдаём их vision-LLM.

    Args:
        pdf_source: путь к PDF или его содержимое как bytes.
        neighbor_window: сколько соседних страниц добавлять вокруг каждой найденной.
        max_pages: ограничение сверху на количество собранных страниц.
        pdf_label: как называть PDF в логах/ошибках если передали bytes.

    Returns:
        PdfExtractionResult с выбранными страницами, текстом и (для сканов)
        page_images в виде PNG-байтов.

    Raises:
        FileNotFoundError: если PDF-файл не существует.
        RuntimeError: если в PDF не нашлось ни одной релевантной страницы
                      (и он не выглядит сканом).
    """
    if isinstance(pdf_source, Path):
        if not pdf_source.exists():
            raise FileNotFoundError(f"PDF не найден: {pdf_source}")
        doc = pymupdf.open(str(pdf_source))
        label = pdf_source.name
        logical_path: Path = pdf_source
    else:
        doc = pymupdf.open(stream=pdf_source, filetype="pdf")
        label = pdf_label
        logical_path = Path(pdf_label)

    try:
        total_pages = doc.page_count
        page_texts: list[str] = []
        for page in doc:
            page_texts.append(page.get_text("text") or "")

        matched_sections: dict[int, list[str]] = {}
        hits_by_page: dict[int, dict[int, int]] = {}
        for idx, raw in enumerate(page_texts):
            norm = _normalize(raw)
            matches, hits_by_group = _find_matches(norm)
            if matches:
                matched_sections[idx] = matches
                hits_by_page[idx] = hits_by_group

        garbled = _looks_like_garbled_encoding(page_texts)
        is_scan = (
            (_looks_like_scan(page_texts) or garbled) and not matched_sections
        )
        if garbled and not matched_sections:
            logger.warning(
                "PDF=%s: текст извлечён, но почти без кириллицы "
                "(битая кодировка/ToUnicode) — переключаемся на vision.",
                label,
            )

        # ─── Ветка 1: обычный текстовый PDF ──────────────────────────────
        if matched_sections:
            selected = _expand_neighbors(
                matched_sections.keys(), total=total_pages, window=neighbor_window
            )

            if len(selected) > max_pages:
                top_pages = _prioritized_pages(matched_sections, hits_by_page, max_pages)
                selected = _expand_neighbors(
                    top_pages, total=total_pages, window=neighbor_window
                )[:max_pages]
                logger.warning(
                    "Слишком много кандидатов, ограничили до %d страниц "
                    "(по одной лучшей странице на раздел + добор по совпадениям).",
                    max_pages,
                )

            chunks: list[str] = []
            for idx in selected:
                marker = f"\n\n───── СТРАНИЦА {idx + 1} из {total_pages} ─────\n"
                body = page_texts[idx].strip()
                if len(body) < _SCAN_PAGE_TEXT_THRESHOLD:
                    body = (
                        "[НА ЭТОЙ СТРАНИЦЕ МАЛО ИЗВЛЕКАЕМОГО ТЕКСТА — "
                        "смотри прикреплённое изображение страницы]"
                    )
                chunks.append(marker + body)

            text = "\n".join(chunks).strip()

            # Гибрид: в «текстовом» PDF отдельные таблицы бывают растровыми
            # (НОВАТЭК: баланс — картинка, ОПиУ — текст). Рендерим только
            # пустые выбранные страницы, чтобы vision-модель их прочитала.
            sparse = [
                idx for idx in selected
                if len(page_texts[idx].strip()) < _SCAN_PAGE_TEXT_THRESHOLD
            ]
            page_images: list[bytes] = []
            for idx in sparse[:_MAX_SCAN_PAGES_FOR_VISION]:
                try:
                    page_images.append(_render_page_png(doc[idx]))
                except Exception as exc:  # noqa: BLE001
                    logger.error("Не смог отрендерить страницу %d: %s", idx + 1, exc)

            if page_images:
                logger.warning(
                    "PDF=%s: гибридный режим — %d выбранных страниц без текста "
                    "отправлены как PNG (vision).",
                    label, len(page_images),
                )

            logger.info(
                "PDF=%s: всего страниц %d, выбрано %d (по ключам: %d), vision=%d.",
                label, total_pages, len(selected), len(matched_sections),
                len(page_images),
            )

            return PdfExtractionResult(
                pdf_path=logical_path,
                total_pages=total_pages,
                selected_pages=selected,
                text=text,
                matched_sections=matched_sections,
                # True → extractor_service приложит page_images к запросу LLM.
                is_scanned=bool(page_images),
                page_images=page_images,
            )

        # ─── Ветка 2: скан-PDF — рендерим страницы для vision-LLM ─────────
        if is_scan:
            # Для скан-PDF берём первые N страниц (обычно отчёт начинается
            # с титула/оглавления, после них идут баланс и ОПиУ).
            # _MAX_SCAN_PAGES_FOR_VISION подобран так, чтобы суммарный запрос
            # помещался в TPM-лимит OpenAI даже при параллельных вызовах.
            n = min(_MAX_SCAN_PAGES_FOR_VISION, total_pages)
            selected = list(range(n))

            logger.warning(
                "PDF=%s: выглядит как СКАН (мало извлекаемого текста). "
                "Рендерим %d страниц в PNG для vision-LLM (gpt-4o-mini).",
                label, n,
            )

            page_images: list[bytes] = []
            for idx in selected:
                try:
                    page_images.append(_render_page_png(doc[idx]))
                except Exception as exc:  # noqa: BLE001
                    logger.error("Не смог отрендерить страницу %d: %s", idx, exc)

            # Текст даже если коряво извлечённый, всё равно отдадим как hint.
            chunks = [
                f"───── СТРАНИЦА {idx + 1} из {total_pages} ─────\n"
                + page_texts[idx].strip()
                for idx in selected
            ]
            text = "\n".join(chunks).strip() or (
                "[PDF-скан — текст не извлекается, страницы отправлены как "
                "изображения ниже. Читай данные прямо из картинок.]"
            )

            return PdfExtractionResult(
                pdf_path=logical_path,
                total_pages=total_pages,
                selected_pages=selected,
                text=text,
                matched_sections={},
                is_scanned=True,
                page_images=page_images,
            )

        # ─── Ветка 3: текст есть, но ключевые слова не найдены ────────────
        raise RuntimeError(
            f"В PDF {label} не найдено страниц с финансовыми таблицами "
            f"(по ключевым фразам). Проверь отчёт вручную."
        )
    finally:
        doc.close()


# ─── Раздел примечаний «1. Информация о компании» ───────────────────────────

COMPANY_INFO_START_PHRASES: tuple[str, ...] = (
    "информация о компании",
    "информация о группе",
    "information about the company",
    "information about the group",
    "information about the issuer",
    "company information",
    "group information",
)

# Следующий нумерованный раздел примечаний (2. …) — граница секции.
_NEXT_NOTES_SECTION_RE = re.compile(
    r"(?:^|\n)\s*2\.\s+[A-Za-zА-Яа-яЁё]",
    re.MULTILINE,
)

_MAX_COMPANY_INFO_PAGES = 8


@dataclass
class CompanyInfoExtractionResult:
    """Фрагмент PDF с описанием компании из примечаний."""
    selected_pages: list[int]
    text: str
    is_scanned: bool = False
    page_images: list[bytes] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.page_images is None:
            self.page_images = []


def _page_has_company_info_start(page_text_norm: str) -> bool:
    return any(phrase in page_text_norm for phrase in COMPANY_INFO_START_PHRASES)


def _truncate_at_next_notes_section(text: str) -> str:
    m = _NEXT_NOTES_SECTION_RE.search(text)
    if m:
        return text[: m.start()].strip()
    return text.strip()


def extract_company_info_pages(
    pdf_source: Union[Path, bytes],
    *,
    pdf_label: str = "in-memory PDF",
    max_pages: int = _MAX_COMPANY_INFO_PAGES,
) -> Optional[CompanyInfoExtractionResult]:
    """Выбрать страницы с разделом «1. Информация о компании» из примечаний.

    Returns:
        CompanyInfoExtractionResult или None, если раздел не найден.
    """
    if isinstance(pdf_source, Path):
        if not pdf_source.exists():
            raise FileNotFoundError(f"PDF не найден: {pdf_source}")
        doc = pymupdf.open(str(pdf_source))
        label = pdf_source.name
    else:
        doc = pymupdf.open(stream=pdf_source, filetype="pdf")
        label = pdf_label

    try:
        total_pages = doc.page_count
        page_texts: list[str] = []
        for page in doc:
            page_texts.append(page.get_text("text") or "")

        start_idx: Optional[int] = None
        for idx, raw in enumerate(page_texts):
            if _page_has_company_info_start(_normalize(raw)):
                start_idx = idx
                break

        if start_idx is None:
            logger.info("PDF=%s: раздел «Информация о компании» не найден.", label)
            return None

        selected: list[int] = [start_idx]
        combined = page_texts[start_idx]

        for idx in range(start_idx + 1, min(total_pages, start_idx + max_pages)):
            chunk = page_texts[idx]
            if _NEXT_NOTES_SECTION_RE.search(_normalize(chunk)):
                break
            selected.append(idx)
            combined += "\n\n" + chunk

        text = _truncate_at_next_notes_section(combined.strip())
        if not text:
            return None

        is_scan = len(text.strip()) < _SCAN_PAGE_TEXT_THRESHOLD
        page_images: list[bytes] = []
        if is_scan:
            for idx in selected:
                page_images.append(_render_page_png(doc[idx]))

        logger.info(
            "PDF=%s: раздел «Информация о компании» — страницы %s (скан=%s).",
            label,
            [p + 1 for p in selected],
            is_scan,
        )

        return CompanyInfoExtractionResult(
            selected_pages=selected,
            text=text,
            is_scanned=is_scan and bool(page_images),
            page_images=page_images,
        )
    finally:
        doc.close()
