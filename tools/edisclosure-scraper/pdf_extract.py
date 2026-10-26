"""
Извлечение основного PDF из архива → TICKER_{period_key}.pdf
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

_NAME_HINTS = (
    "консолид", "consolid", "ifrs", "мсфо", "msfo", "финанс", "financial",
    "annual", "годов", "year", "отчет", "отчёт", "report", "промежут", "interim",
)


def pdf_target_path(
    ticker: str,
    year_or_key: Union[int, str],
    ticker_dir: Path,
    *,
    period_key: Optional[str] = None,
) -> Path:
    """Имя: TICKER_YYYY.pdf или TICKER_YYYY_Q1.pdf / TICKER_YYYY_H1.pdf."""
    key = period_key or str(year_or_key)
    return ticker_dir / f"{ticker.upper()}_{key}.pdf"


def pdf_exists(
    ticker: str,
    year_or_key: Union[int, str],
    ticker_dir: Path,
    *,
    period_key: Optional[str] = None,
) -> bool:
    return pdf_target_path(
        ticker, year_or_key, ticker_dir, period_key=period_key
    ).is_file()


def _score_pdf(path: Path) -> tuple[float, int]:
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


def _unpack(archive: Path, into: Path) -> None:
    """Распаковать архив раскрытия. Обычно это zip, но e-disclosure отдаёт и
    RAR под тем же именем: у Русснефти полугодия 2025 и 2026 — «Rar!» (RAR 7)
    внутри `*_consolidated.zip`."""
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(into)
        return
    with archive.open("rb") as handle:
        head = handle.read(8)
    if head.startswith(b"Rar!"):
        import subprocess

        # unrar (non-free) понимает любые версии, включая RAR 7; unar — RAR до
        # пятой; 7z из Debian собран без RAR вовсе (+dfsg). Берём первый,
        # что есть и справился.
        tools = (
            ("unrar", lambda exe: [exe, "x", "-o+", "-inul", str(archive), f"{into}/"]),
            ("unar", lambda exe: [exe, "-q", "-f", "-o", str(into), str(archive)]),
            ("7z", lambda exe: [exe, "x", "-y", f"-o{into}", str(archive)]),
        )
        for name, command in tools:
            exe = shutil.which(name)
            if not exe:
                continue
            done = subprocess.run(command(exe), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if done.returncode == 0:
                return
        raise OSError("RAR не распаковался: установите unrar (раздел non-free) или unar")
    raise zipfile.BadZipFile("File is not a zip file")


def extract_main_pdf_from_zip(
    zip_path: Path,
    ticker: str,
    year: int,
    ticker_dir: Path,
    *,
    delete_zip: bool = True,
    period_key: Optional[str] = None,
) -> Path | None:
    key = period_key or str(year)
    target = pdf_target_path(ticker, year, ticker_dir, period_key=key)
    if target.exists():
        if delete_zip and zip_path.exists():
            try:
                zip_path.unlink()
            except OSError as exc:
                logger.warning("[%s %s] Не удалось удалить zip: %s", ticker, key, exc)
        return target

    if not zip_path.is_file():
        logger.warning("[%s %s] Архив не найден: %s", ticker, key, zip_path)
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="edisclosure_") as tmp:
            tmp_path = Path(tmp)
            _unpack(zip_path, tmp_path)

            pdfs = _collect_pdfs(tmp_path)
            if not pdfs:
                logger.warning("[%s %s] В архиве нет PDF: %s", ticker, key, zip_path.name)
                return None

            best = max(pdfs, key=lambda p: _score_pdf(p))
            ticker_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best, target)
            logger.info(
                "[%s %s] ✓ PDF из архива → %s (из %d файлов, источник: %s)",
                ticker, key, target.name, len(pdfs), best.name,
            )

        if delete_zip:
            zip_path.unlink()

        return target

    except zipfile.BadZipFile as exc:
        logger.error("[%s %s] Повреждённый zip %s: %s", ticker, key, zip_path, exc)
        return None
    except OSError as exc:
        logger.error("[%s %s] Ошибка при распаковке %s: %s", ticker, key, zip_path, exc)
        return None


def process_orphan_zips_in_ticker_dir(ticker: str, ticker_dir: Path) -> int:
    count = 0
    pattern = re.compile(
        r"^(\d{4})(?:_(Q[13]|H1))?_consolidated\.zip$", re.I
    )
    legacy = re.compile(r"^(\d{4})_annual_consolidated\.zip$", re.I)
    for z in sorted(ticker_dir.glob("*_consolidated.zip")):
        m = pattern.match(z.name) or legacy.match(z.name)
        if not m:
            continue
        year = int(m.group(1))
        suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        key = f"{year}_{suffix}" if suffix else str(year)
        if pdf_exists(ticker, year, ticker_dir, period_key=key):
            continue
        if extract_main_pdf_from_zip(
            z, ticker, year, ticker_dir, delete_zip=True, period_key=key
        ):
            count += 1
    return count
