"""Сканирование каталога отчётов: /root/{TICKER}/*.pdf."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.enums import company_type_to_report_type
from app.models.financial_report import FinancialReport

_YEAR_RE = re.compile(r"(19|20)\d{2}")


def extract_year_from_filename(name: str) -> Optional[int]:
    """Первый правдоподобный год 1990..текущий в имени файла."""
    current = date.today().year
    for match in _YEAR_RE.finditer(name):
        y = int(match.group(0))
        if 1990 <= y <= current:
            return y
    return None


@dataclass
class ScannedPdf:
    ticker: str
    company_id: Optional[int]
    fiscal_year: Optional[int]
    pdf_path: str
    # company_not_found | company_has_reports | no_year | bank
    skip_reason: Optional[str] = None


@dataclass
class ScanPreview:
    reports_root: str
    ticker_dirs: int
    pdf_files: int
    queued: int
    skipped_company_has_reports: int
    skipped_company_not_found: int
    skipped_no_year: int
    skipped_banks: int
    companies_with_reports_in_db: int
    items: list[ScannedPdf]


def companies_with_any_reports(db: Session) -> set[int]:
    rows = (
        db.query(FinancialReport.company_id)
        .group_by(FinancialReport.company_id)
        .having(func.count(FinancialReport.id) > 0)
        .all()
    )
    return {int(r[0]) for r in rows}


def ticker_to_company_map(db: Session) -> dict[str, Company]:
    companies = db.query(Company).all()
    out: dict[str, Company] = {}
    for c in companies:
        if c.ticker:
            out[str(c.ticker).strip().upper()] = c
    return out


def scan_reports_dir(
    db: Session,
    reports_root: Path,
    *,
    skip_companies_with_reports: bool = True,
    skip_banks: bool = True,
    include_skipped_in_items: bool = False,
) -> ScanPreview:
    """
    Обходит подкаталоги тикеров и собирает PDF.

    При skip_companies_with_reports=True целые тикеры с уже существующими
    отчётами в БД не попадают в очередь.

    При skip_banks=True пропускаются компании с report_type=bank
    (сектор financial/banks) — Грэм-скрининг для них отдельно.
    """
    root = reports_root.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Каталог отчётов не найден: {root}")

    by_ticker = ticker_to_company_map(db)
    with_reports = companies_with_any_reports(db)

    queued_items: list[ScannedPdf] = []
    skipped_items: list[ScannedPdf] = []
    ticker_dirs = 0
    pdf_files = 0
    skipped_has_reports = 0
    skipped_not_found = 0
    skipped_no_year = 0
    skipped_banks = 0

    for entry in sorted(root.iterdir(), key=lambda p: p.name.upper()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        ticker = entry.name.strip().upper()
        ticker_dirs += 1
        company = by_ticker.get(ticker)

        pdfs = sorted(
            [p for p in entry.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"],
            key=lambda p: (extract_year_from_filename(p.name) or 9999, p.name),
        )
        if not pdfs:
            continue

        if company is None:
            skipped_not_found += len(pdfs)
            pdf_files += len(pdfs)
            if include_skipped_in_items:
                for p in pdfs:
                    skipped_items.append(
                        ScannedPdf(
                            ticker=ticker,
                            company_id=None,
                            fiscal_year=extract_year_from_filename(p.name),
                            pdf_path=str(p.resolve()),
                            skip_reason="company_not_found",
                        )
                    )
            continue

        if skip_banks and company_type_to_report_type(company.company_type) == "bank":
            skipped_banks += len(pdfs)
            pdf_files += len(pdfs)
            if include_skipped_in_items:
                for p in pdfs:
                    skipped_items.append(
                        ScannedPdf(
                            ticker=ticker,
                            company_id=int(company.id),  # type: ignore[arg-type]
                            fiscal_year=extract_year_from_filename(p.name),
                            pdf_path=str(p.resolve()),
                            skip_reason="bank",
                        )
                    )
            continue

        if skip_companies_with_reports and company.id in with_reports:
            skipped_has_reports += len(pdfs)
            pdf_files += len(pdfs)
            if include_skipped_in_items:
                for p in pdfs:
                    skipped_items.append(
                        ScannedPdf(
                            ticker=ticker,
                            company_id=int(company.id),  # type: ignore[arg-type]
                            fiscal_year=extract_year_from_filename(p.name),
                            pdf_path=str(p.resolve()),
                            skip_reason="company_has_reports",
                        )
                    )
            continue

        for p in pdfs:
            pdf_files += 1
            year = extract_year_from_filename(p.name)
            if year is None:
                skipped_no_year += 1
                if include_skipped_in_items:
                    skipped_items.append(
                        ScannedPdf(
                            ticker=ticker,
                            company_id=int(company.id),  # type: ignore[arg-type]
                            fiscal_year=None,
                            pdf_path=str(p.resolve()),
                            skip_reason="no_year",
                        )
                    )
                continue
            queued_items.append(
                ScannedPdf(
                    ticker=ticker,
                    company_id=int(company.id),  # type: ignore[arg-type]
                    fiscal_year=year,
                    pdf_path=str(p.resolve()),
                )
            )

    items = queued_items + (skipped_items if include_skipped_in_items else [])
    return ScanPreview(
        reports_root=str(root),
        ticker_dirs=ticker_dirs,
        pdf_files=pdf_files,
        queued=len(queued_items),
        skipped_company_has_reports=skipped_has_reports,
        skipped_company_not_found=skipped_not_found,
        skipped_no_year=skipped_no_year,
        skipped_banks=skipped_banks,
        companies_with_reports_in_db=len(with_reports),
        items=items,
    )
