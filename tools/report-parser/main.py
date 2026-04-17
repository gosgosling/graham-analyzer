"""CLI-входная точка сервиса AI-парсинга финансовых отчётов.

Обходит папку с отчётами (по умолчанию `/home/devops/Reports`), находит PDF
для каждого тикера и года и запускает пайплайн извлечения из
`app.services.report_parser.parse_pdf_to_report`.

Ожидаемая структура папок:
    REPORTS_DIR/
        {TICKER}/
            {YEAR}_annual_consolidated/
                any_report.pdf
            {YEAR}_annual_consolidated.zip  # архивы игнорируются

Если папка `{YEAR}_annual_consolidated` не распакована (есть только zip),
тикер/год пропускается с warning.

Примеры:
    python main.py --ticker LKOH --year 2023 --dry-run
    python main.py --ticker GAZP
    python main.py --pdf /path/to/report.pdf --ticker LKOH --year 2023
    python main.py                                # все тикеры и годы
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Iterable, Optional

import config  # noqa: F401  # настраивает sys.path, loads env
from config import cli_settings
from db_client import SessionLocal, get_company_by_ticker
from app.config import settings as backend_settings
from app.services.report_parser import (
    ComparisonResult,
    compare_pdf_with_existing,
    parse_pdf_to_report,
)
from app.services.report_parser.extractor_service import (
    ExtractionOutcome,
    ReportAlreadyExistsError,
    ReportNotFoundForComparison,
)
from app.services.report_parser.llm_client import (
    LLMNotConfiguredError,
    LLMParseError,
    LLMTransientError,
)

logger = logging.getLogger(__name__)


_YEAR_DIR_PATTERN = re.compile(r"^(\d{4})_annual_consolidated$")


def iter_ticker_dirs(reports_dir: Path) -> Iterable[Path]:
    if not reports_dir.exists():
        raise FileNotFoundError(f"REPORTS_DIR не найден: {reports_dir}")
    for entry in sorted(reports_dir.iterdir()):
        if entry.is_dir():
            yield entry


def iter_year_dirs(ticker_dir: Path) -> Iterable[tuple[int, Path]]:
    """Вернуть (year, path) для папок '{YEAR}_annual_consolidated'."""
    for entry in sorted(ticker_dir.iterdir()):
        if not entry.is_dir():
            continue
        m = _YEAR_DIR_PATTERN.match(entry.name)
        if m:
            yield int(m.group(1)), entry


def find_pdf_in_year_dir(year_dir: Path) -> Optional[Path]:
    pdfs = sorted(year_dir.glob("*.pdf"))
    if not pdfs:
        return None
    if len(pdfs) > 1:
        logger.warning(
            "В %s найдено несколько PDF, беру первый: %s",
            year_dir, pdfs[0].name,
        )
    return pdfs[0]


def collect_tasks(
    reports_dir: Path,
    *,
    ticker_filter: Optional[str] = None,
    year_filter: Optional[int] = None,
) -> list[tuple[str, int, Path]]:
    tasks: list[tuple[str, int, Path]] = []
    ticker_filter_upper = ticker_filter.upper() if ticker_filter else None

    for ticker_dir in iter_ticker_dirs(reports_dir):
        ticker = ticker_dir.name.upper()
        if ticker_filter_upper and ticker != ticker_filter_upper:
            continue

        for year, year_dir in iter_year_dirs(ticker_dir):
            if year_filter is not None and year != year_filter:
                continue
            pdf = find_pdf_in_year_dir(year_dir)
            if not pdf:
                logger.warning(
                    "[%s %s] PDF не найден в %s — пропускаем.",
                    ticker, year, year_dir,
                )
                continue
            tasks.append((ticker, year, pdf))
    return tasks


def process_task(
    *,
    ticker: str,
    year: int,
    pdf_path: Path,
    dry_run: bool,
    force: bool,
) -> ExtractionOutcome:
    """Выполнить один ticker+year+pdf. Каждый таск — своя DB-сессия."""
    with SessionLocal() as db:
        company = get_company_by_ticker(db, ticker)
        if not company:
            return ExtractionOutcome(
                ticker=ticker,
                fiscal_year=year,
                report_type="general",
                dry_run=dry_run,
                pdf_label=pdf_path.name,
                skipped_reason=(
                    f"Тикер {ticker} не найден в БД companies. "
                    f"Синхронизируй компании через backend, затем повтори."
                ),
            )

        try:
            return parse_pdf_to_report(
                db=db,
                pdf_source=pdf_path,
                company=company,
                fiscal_year=year,
                dry_run=dry_run,
                force=force,
            )
        except ReportAlreadyExistsError as exc:
            return ExtractionOutcome(
                ticker=ticker, fiscal_year=year,
                report_type="general", dry_run=dry_run,
                pdf_label=pdf_path.name,
                skipped_reason=str(exc),
            )
        except (LLMTransientError, LLMParseError, LLMNotConfiguredError) as exc:
            logger.error("[%s %s] LLM error: %s", ticker, year, exc)
            return ExtractionOutcome(
                ticker=ticker, fiscal_year=year,
                report_type="general", dry_run=dry_run,
                pdf_label=pdf_path.name,
                skipped_reason=f"LLM error: {exc}",
            )
        except Exception as exc:
            logger.exception("[%s %s] Ошибка обработки: %s", ticker, year, exc)
            db.rollback()
            return ExtractionOutcome(
                ticker=ticker, fiscal_year=year,
                report_type="general", dry_run=dry_run,
                pdf_label=pdf_path.name,
                skipped_reason=f"Exception: {exc}",
            )


# ─── Режим сравнения ────────────────────────────────────────────────────────


_STATUS_ICON: dict[str, str] = {
    "match": "✓",
    "close": "≈",
    "mismatch": "✗",
    "missing_ai": "·AI",
    "missing_existing": "·DB",
    "both_missing": " — ",
}


def _fmt_value(value: object, kind: str) -> str:
    if value is None:
        return "—"
    numeric: Optional[float]
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        numeric = None

    if kind == "money_mln" and numeric is not None:
        abs_v = abs(numeric)
        if abs_v >= 1_000_000:
            return f"{numeric/1_000_000:,.2f} трлн".replace(",", " ")
        if abs_v >= 1_000:
            return f"{numeric/1_000:,.2f} млрд".replace(",", " ")
        return f"{numeric:,.1f} млн".replace(",", " ")
    if kind == "int" and numeric is not None:
        return f"{int(numeric):,}".replace(",", " ")
    if kind == "float" and numeric is not None:
        return f"{numeric:,.2f}".replace(",", " ")
    return str(value)


def _print_comparison(result: ComparisonResult) -> None:
    """Вывести diff красивой табличкой в лог."""
    s = result.summary
    header = (
        f"\n══════ COMPARE {result.ticker} / {result.fiscal_year} ══════\n"
        f"  Existing report id={result.existing_report_id} "
        f"(verified={'yes' if result.existing_report_verified else 'NO'})\n"
        f"  Report type:   {result.report_type}\n"
        f"  PDF:           {result.pdf_label} — использовано {result.selected_pages}/{result.total_pages} стр.\n"
        f"  Summary:       matched={s.matched}  close={s.close}  "
        f"mismatched={s.mismatched}  missing_ai={s.missing_in_ai}  "
        f"missing_existing={s.missing_in_existing}  both_missing={s.both_missing}"
    )
    if s.max_pct_diff is not None:
        header += f"\n  Max pct diff:  {s.max_pct_diff:+.2f}%"
    logger.info(header)

    logger.info("  %-3s  %-32s  %-20s  %-20s  %-10s", "st", "Field", "Existing (DB)", "Extracted (AI)", "Δ %")
    logger.info("  %s", "-" * 95)
    for d in result.diffs:
        pct = f"{d.pct_diff:+.2f}%" if d.pct_diff is not None else ""
        logger.info(
            "  %-3s  %-32s  %-20s  %-20s  %-10s",
            _STATUS_ICON.get(d.status, "?"),
            d.label[:32],
            _fmt_value(d.existing_value, d.kind)[:20],
            _fmt_value(d.extracted_value, d.kind)[:20],
            pct,
        )
        if d.note:
            logger.info("       ↪ %s", d.note)


def process_compare_task(
    *,
    ticker: str,
    year: int,
    pdf_path: Path,
) -> Optional[ComparisonResult]:
    with SessionLocal() as db:
        company = get_company_by_ticker(db, ticker)
        if not company:
            logger.warning("[%s %s] Тикер не найден в БД, пропускаем.", ticker, year)
            return None
        try:
            return compare_pdf_with_existing(
                db=db,
                pdf_source=pdf_path,
                company=company,
                fiscal_year=year,
            )
        except ReportNotFoundForComparison as exc:
            logger.warning("[%s %s] %s", ticker, year, exc)
            return None
        except (LLMTransientError, LLMParseError, LLMNotConfiguredError) as exc:
            logger.error("[%s %s] LLM error: %s", ticker, year, exc)
            return None
        except Exception as exc:
            logger.exception("[%s %s] Ошибка сравнения: %s", ticker, year, exc)
            return None


# ─── CLI ────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI-парсер финансовых отчётов для graham-analyzer",
    )
    parser.add_argument("--ticker", help="Тикер (например, LKOH)")
    parser.add_argument("--year", type=int, help="Отчётный год (например, 2023)")
    parser.add_argument(
        "--pdf", type=Path,
        help="Путь к конкретному PDF (ticker и year тогда обязательны)",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=cli_settings.reports_dir,
        help=f"Корневая папка с отчётами (по умолчанию: {cli_settings.reports_dir})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Только извлечь и показать, НЕ писать в БД",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Пересоздать отчёт, если он уже есть в БД",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help=(
            "Режим сравнения: прогнать PDF через модель и сравнить "
            "с уже имеющимся в БД отчётом. Ничего не пишется. "
            "Полезно для оценки качества модели на проверенных отчётах."
        ),
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _banner() -> None:
    logger.info("=" * 70)
    logger.info("AI-парсер финансовых отчётов")
    logger.info("  LLM:       %s / %s", backend_settings.LLM_PROVIDER, backend_settings.LLM_MODEL)
    logger.info("  Base URL:  %s", backend_settings.LLM_BASE_URL)
    logger.info("  Reports:   %s", cli_settings.reports_dir)
    logger.info("=" * 70)


def main() -> int:
    args = parse_args()
    _setup_logging(args.log_level)
    _banner()

    if not backend_settings.llm_configured:
        logger.error(
            "LLM не сконфигурирован: задай LLM_API_KEY и LLM_MODEL в корневом .env "
            "или в tools/report-parser/.env."
        )
        return 2

    if args.pdf:
        if not args.ticker or not args.year:
            logger.error("--pdf требует --ticker и --year.")
            return 2
        tasks = [(args.ticker.upper(), args.year, args.pdf.resolve())]
    else:
        try:
            tasks = collect_tasks(
                args.reports_dir,
                ticker_filter=args.ticker,
                year_filter=args.year,
            )
        except FileNotFoundError as exc:
            logger.error(str(exc))
            return 2

    if not tasks:
        logger.warning("Не найдено ни одного PDF для обработки с текущими фильтрами.")
        return 1

    logger.info("К обработке: %d PDF.", len(tasks))

    if args.compare:
        if args.dry_run or args.force:
            logger.warning("Флаги --dry-run / --force в режиме --compare игнорируются.")
        compared = 0
        no_existing = 0
        failed = 0
        total_matched = 0
        total_close = 0
        total_mismatched = 0
        total_missing_ai = 0

        for ticker, year, pdf in tasks:
            logger.info("───── COMPARE %s / %d / %s ─────", ticker, year, pdf.name)
            result = process_compare_task(ticker=ticker, year=year, pdf_path=pdf)
            if result is None:
                no_existing += 1
                continue
            _print_comparison(result)
            compared += 1
            total_matched += result.summary.matched
            total_close += result.summary.close
            total_mismatched += result.summary.mismatched
            total_missing_ai += result.summary.missing_in_ai

        logger.info("=" * 70)
        logger.info(
            "COMPARE готово. Сравнено: %d | пропущено (нет в БД/ошибки): %d",
            compared, no_existing,
        )
        if compared:
            logger.info(
                "Итого по полям: match=%d  close=%d  mismatch=%d  missing_ai=%d",
                total_matched, total_close, total_mismatched, total_missing_ai,
            )
        logger.info("В БД ничего не записано (режим --compare).")
        return 0 if failed == 0 else 1

    created = 0
    skipped = 0
    failed = 0

    for ticker, year, pdf in tasks:
        logger.info("───── %s / %d / %s ─────", ticker, year, pdf.name)
        outcome = process_task(
            ticker=ticker, year=year, pdf_path=pdf,
            dry_run=args.dry_run, force=args.force,
        )
        if outcome.success:
            created += 1 if not outcome.dry_run else 0
        elif outcome.skipped_reason:
            skipped += 1
        else:
            failed += 1

    logger.info("=" * 70)
    logger.info(
        "Готово. Обработано: %d | создано: %d | пропущено: %d | ошибок: %d",
        len(tasks), created, skipped, failed,
    )
    if args.dry_run:
        logger.info("Режим --dry-run: в БД ничего не записано.")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
