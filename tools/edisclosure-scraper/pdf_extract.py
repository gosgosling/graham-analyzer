"""
Извлечение основного PDF годового консолидированного отчёта из архива (zip).

Логика выбора файла при нескольких PDF:
- приоритет имени (консолидирован / МСФО / IFRS / financial / annual);
- иначе самый крупный файл (обычно полный отчёт).
После успешного извлечения архив удаляется (остаётся только PDF в папке тикера).
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Подсказки в имени файла (латиница и кириллица)
_NAME_HINTS = (
    "консолид", "consolid", "ifrs", "мсфо", "msfo", "финанс", "financial",
    "annual", "годов", "year", "отчет", "отчёт", "report",
)


def pdf_target_path(ticker: str, year: int, ticker_dir: Path) -> Path:
    """Имя файла: TICKER_YYYY.pdf"""
    return ticker_dir / f"{ticker.upper()}_{year}.pdf"


def pdf_exists(ticker: str, year: int, ticker_dir: Path) -> bool:
    return pdf_target_path(ticker, year, ticker_dir).is_file()


def _score_pdf(path: Path) -> tuple[float, int]:
    """Выше — лучше. Сначала совпадения в имени, затем размер."""
    name = path.name.lower()
    hint_score = sum(10 for h in _NAME_HINTS if h in name)
    size = path.stat().st_size if path.exists() else 0
    return (hint_score + size / 1_000_000_000.0, size)


def _collect_pdfs(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() == ".pdf":
            out.append(p)
    return out


def extract_main_pdf_from_zip(
    zip_path: Path,
    ticker: str,
    year: int,
    ticker_dir: Path,
    *,
    delete_zip: bool = True,
) -> Path | None:
    """
    Распаковывает zip, выбирает основной PDF, сохраняет как TICKER_YEAR.pdf.
    При успехе удаляет zip (если delete_zip).
    """
    target = pdf_target_path(ticker, year, ticker_dir)
    if target.exists():
        if delete_zip and zip_path.exists():
            try:
                zip_path.unlink()
                logger.debug("[%s %s] Удалён старый zip (PDF уже есть).", ticker, year)
            except OSError as exc:
                logger.warning("[%s %s] Не удалось удалить zip: %s", ticker, year, exc)
        return target

    if not zip_path.is_file():
        logger.warning("[%s %s] Архив не найден: %s", ticker, year, zip_path)
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="edisclosure_") as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(zip_path, "r") as zf:
                # Архивы с e-disclosure.ru — доверенный источник; extractall достаточен.
                zf.extractall(tmp_path)

            pdfs = _collect_pdfs(tmp_path)
            if not pdfs:
                logger.warning("[%s %s] В архиве нет PDF: %s", ticker, year, zip_path.name)
                return None

            best = max(pdfs, key=lambda p: _score_pdf(p))
            ticker_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best, target)
            logger.info(
                "[%s %s] ✓ PDF из архива → %s (из %d файлов, источник: %s)",
                ticker, year, target.name, len(pdfs), best.name,
            )

        if delete_zip:
            zip_path.unlink()
            logger.debug("[%s %s] Удалён архив %s", ticker, year, zip_path.name)

        return target

    except zipfile.BadZipFile as exc:
        logger.error("[%s %s] Повреждённый zip %s: %s", ticker, year, zip_path, exc)
        return None
    except OSError as exc:
        logger.error("[%s %s] Ошибка при распаковке %s: %s", ticker, year, zip_path, exc)
        return None


def process_orphan_zips_in_ticker_dir(ticker: str, ticker_dir: Path) -> int:
    """
    Для архивов вида YYYY_annual_consolidated.zip без готового TICKER_YYYY.pdf
    пытается извлечь PDF. Возвращает число обработанных архивов.
    """
    count = 0
    pattern = re.compile(r"^(\d{4})_annual_consolidated\.zip$", re.I)
    for z in sorted(ticker_dir.glob("*_annual_consolidated.zip")):
        m = pattern.match(z.name)
        if not m:
            continue
        year = int(m.group(1))
        if pdf_exists(ticker, year, ticker_dir):
            continue
        if extract_main_pdf_from_zip(z, ticker, year, ticker_dir, delete_zip=True):
            count += 1
    return count
