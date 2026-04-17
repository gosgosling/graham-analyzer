"""AI-парсер финансовых отчётов из PDF.

Публичные функции:
  * `parse_pdf_to_report` — основной пайплайн: PDF → черновик отчёта в БД
    (auto_extracted=True, verified_by_analyst=False).
  * `extract_financial_pages` — выбор релевантных страниц PDF.
  * `ExtractedReport` — pydantic-схема результата извлечения LLM.
"""
from app.services.report_parser.extractor_service import (
    ComparisonResult,
    ComparisonSummary,
    ExtractionOutcome,
    ReportFieldDiff,
    ReportNotFoundForComparison,
    compare_pdf_with_existing,
    compute_report_diff,
    parse_pdf_to_report,
)
from app.services.report_parser.pdf_extractor import (
    PdfExtractionResult,
    extract_financial_pages,
)
from app.services.report_parser.schemas import ExtractedReport

__all__ = (
    "ComparisonResult",
    "ComparisonSummary",
    "ExtractedReport",
    "ExtractionOutcome",
    "PdfExtractionResult",
    "ReportFieldDiff",
    "ReportNotFoundForComparison",
    "compare_pdf_with_existing",
    "compute_report_diff",
    "extract_financial_pages",
    "parse_pdf_to_report",
)
