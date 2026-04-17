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
from typing import Iterable, Union

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
    (
        "итого активы",
        "итого обязательства",
        "итого капитал",
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


def _normalize(text: str) -> str:
    """Нормализация для сравнения: нижний регистр, ё→е, единый пробел."""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def _find_matches(page_text_norm: str) -> list[str]:
    matches: list[str] = []
    for group in SECTION_KEYWORDS:
        for phrase in group:
            if phrase in page_text_norm:
                matches.append(phrase)
    return matches


def _expand_neighbors(indices: Iterable[int], total: int, window: int = 1) -> list[int]:
    selected: set[int] = set()
    for i in indices:
        for j in range(i - window, i + window + 1):
            if 0 <= j < total:
                selected.add(j)
    return sorted(selected)


def extract_financial_pages(
    pdf_source: Union[Path, bytes],
    neighbor_window: int = 1,
    max_pages: int = 60,
    *,
    pdf_label: str = "in-memory PDF",
) -> PdfExtractionResult:
    """
    Прочитать PDF (из файла или bytes), выбрать страницы с финансовыми таблицами.

    Args:
        pdf_source: путь к PDF или его содержимое как bytes.
        neighbor_window: сколько соседних страниц добавлять вокруг каждой найденной.
        max_pages: ограничение сверху на количество собранных страниц.
        pdf_label: как называть PDF в логах/ошибках если передали bytes.

    Returns:
        PdfExtractionResult с выбранными страницами и их склеенным текстом.

    Raises:
        FileNotFoundError: если PDF-файл не существует.
        RuntimeError: если в PDF не нашлось ни одной релевантной страницы.
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
    finally:
        doc.close()

    matched_sections: dict[int, list[str]] = {}
    for idx, raw in enumerate(page_texts):
        norm = _normalize(raw)
        matches = _find_matches(norm)
        if matches:
            matched_sections[idx] = matches

    if not matched_sections:
        raise RuntimeError(
            f"В PDF {label} не найдено страниц с финансовыми таблицами "
            f"(по ключевым фразам). Проверь отчёт вручную."
        )

    selected = _expand_neighbors(
        matched_sections.keys(), total=total_pages, window=neighbor_window
    )

    if len(selected) > max_pages:
        ranked = sorted(
            matched_sections.items(),
            key=lambda kv: len(kv[1]),
            reverse=True,
        )
        top_pages = {idx for idx, _ in ranked[:max_pages]}
        selected = _expand_neighbors(top_pages, total=total_pages, window=neighbor_window)
        selected = selected[:max_pages]
        logger.warning(
            "Слишком много кандидатов (%d), ограничили до %d страниц.",
            len(selected), max_pages,
        )

    chunks: list[str] = []
    for idx in selected:
        marker = f"\n\n───── СТРАНИЦА {idx + 1} из {total_pages} ─────\n"
        chunks.append(marker + page_texts[idx].strip())

    text = "\n".join(chunks).strip()

    logger.info(
        "PDF=%s: всего страниц %d, выбрано %d (по ключам: %d).",
        label, total_pages, len(selected), len(matched_sections),
    )

    return PdfExtractionResult(
        pdf_path=logical_path,
        total_pages=total_pages,
        selected_pages=selected,
        text=text,
        matched_sections=matched_sections,
    )
