"""
Точка входа сервиса загрузки консолидированной отчётности с e-disclosure.ru.

Использование:
  python main.py                        # скачать все компании из БД/mock
  python main.py --tickers SBER ROSN    # только указанные тикеры
  python main.py --dry-run              # показать что будет скачано, без скачивания
  python main.py --list-mapped          # показать тикеры с известными ID и выйти
  python main.py --start-from MVID     # продолжить: пропустить тикеры до MVID (включительно с MVID)

Политика robots.txt (https://www.e-disclosure.ru/robots.txt):
  Запрещено: /api/*, /Event/Certificate?*, /Company/Certificate/*,
             /PortalImageHandler.ashx?*, /Company/Search?*
  Используемые пути РАЗРЕШЕНЫ:
    /portal/files.aspx?id=...&type=4   (список файлов компании)
    /portal/FileLoad.ashx?Fileid=...   (скачивание файла)

Задержки подобраны так, чтобы средняя нагрузка составляла ~1 запрос/мин,
что не создаёт DDoS-эффекта.
"""

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path

from config import COMPANY_DELAY_MIN, COMPANY_DELAY_MAX, REPORTS_BASE_DIR
from db_client import get_companies_from_db
from downloader import download_reports
from pdf_extract import process_orphan_zips_in_ticker_dir
from period_parse import filter_coverage_entries
from scraper import fetch_all_reports, fetch_annual_reports

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(__file__).parent / "scraper.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

# ── Mapping ticker → e-disclosure ID ──────────────────────────────────────────
_MAPPING_FILE = Path(__file__).parent / "company_ids.json"


def load_mapping() -> dict[str, int]:
    """Загружает маппинг тикер → ID из company_ids.json (только верифицированные)."""
    with open(_MAPPING_FILE, encoding="utf-8") as f:
        raw = json.load(f)

    mapping: dict[str, int] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(value.get("id"), int):
            mapping[key.upper()] = value["id"]
    return mapping


# ── CLI ────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Загрузка годовых консолидированных отчётов с e-disclosure.ru"
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        metavar="TICKER",
        help="Ограничить список тикеров (например: SBER ROSN GAZP)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать список компаний и отчётов без скачивания",
    )
    parser.add_argument(
        "--list-mapped",
        action="store_true",
        help="Показать все тикеры с известными ID и выйти",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Уровень логирования (по умолчанию: INFO)",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Только распаковать ZIP из папок Reports в TICKER_YEAR.pdf (без скачивания)",
    )
    parser.add_argument(
        "--start-from",
        metavar="TICKER",
        default="",
        help=(
            "Продолжение прогона: пропустить все тикеры до указанного (порядок как в БД с "
            "фильтром company_ids) и обработать начиная с него. Пример: --start-from MVID"
        ),
    )
    parser.add_argument(
        "--list-json",
        action="store_true",
        help="Только listing (все периоды) → JSON в stdout, без скачивания",
    )
    parser.add_argument(
        "--coverage-filter",
        action="store_true",
        help="С --list-json: только годовые + самый свежий interim на тикер",
    )
    parser.add_argument(
        "--all-periods",
        action="store_true",
        help="Скачивать годовые + промежуточные (по умолчанию только годовые)",
    )
    return parser.parse_args()


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(args.log_level)

    mapping = load_mapping()

    if args.list_mapped:
        print("Тикеры с известными e-disclosure ID:")
        for ticker, cid in sorted(mapping.items()):
            print(f"  {ticker:<10} id={cid}")
        return

    if args.extract_only:
        REPORTS_BASE_DIR.mkdir(parents=True, exist_ok=True)
        n = 0
        for sub in sorted(REPORTS_BASE_DIR.iterdir()):
            if sub.is_dir() and sub.name.isascii():
                n += process_orphan_zips_in_ticker_dir(sub.name.upper(), sub)
        logger.info("Распаковка завершена, обработано архивов: %d.", n)
        return

    logger.info("=" * 60)
    logger.info("Сервис загрузки отчётов e-disclosure.ru стартовал.")
    logger.info("Папка для отчётов: %s", REPORTS_BASE_DIR)
    logger.info("robots.txt: /portal/files.aspx и /portal/FileLoad.ashx — РАЗРЕШЕНЫ")
    logger.info("=" * 60)

    REPORTS_BASE_DIR.mkdir(parents=True, exist_ok=True)

    # Получаем список компаний из БД или mock
    all_companies = get_companies_from_db()

    # Фильтрация по тикерам из аргументов командной строки
    if args.tickers:
        requested = {t.upper() for t in args.tickers}
        all_companies = [c for c in all_companies if c.ticker.upper() in requested]
        if not all_companies:
            logger.error("Ни одна из запрошенных компаний не найдена в БД/mock: %s", args.tickers)
            sys.exit(1)

    # Оставляем только те компании, для которых есть маппинг
    companies_to_process = []
    for company in all_companies:
        ticker_upper = company.ticker.upper()
        if ticker_upper in mapping:
            companies_to_process.append((ticker_upper, mapping[ticker_upper], company.name))
        else:
            logger.warning(
                "Тикер %s (%s) отсутствует в company_ids.json — пропускаем. "
                "Добавьте e-disclosure ID вручную.",
                ticker_upper,
                company.name,
            )

    if not companies_to_process:
        logger.error("Нет компаний для обработки. Проверьте company_ids.json.")
        sys.exit(1)

    if args.start_from:
        start_ticker = args.start_from.strip().upper()
        found_at: int | None = None
        for i, (t, _cid, _name) in enumerate(companies_to_process):
            if t == start_ticker:
                found_at = i
                break
        if found_at is None:
            logger.error(
                "Тикер %s не найден в списке к обработке. Проверьте написание и company_ids.json.",
                start_ticker,
            )
            sys.exit(1)
        skipped = found_at
        companies_to_process = companies_to_process[found_at:]
        logger.info(
            "Режим --start-from %s: пропущено тикеров: %d, к обработке: %d.",
            start_ticker,
            skipped,
            len(companies_to_process),
        )

    logger.info("К обработке: %d компаний.", len(companies_to_process))

    # ── Основной цикл ─────────────────────────────────────────────────────────
    total_downloaded = 0
    total_skipped = 0
    list_json_rows: list[dict] = []

    for idx, (ticker, company_id, company_name) in enumerate(companies_to_process, start=1):
        logger.info(
            "─── [%d/%d] %s  (e-disclosure id=%d) ──────────────────",
            idx, len(companies_to_process), ticker, company_id,
        )

        if args.list_json or args.all_periods:
            reports = fetch_all_reports(company_id, ticker)
        else:
            reports = fetch_annual_reports(company_id, ticker)

        if args.coverage_filter:
            reports = filter_coverage_entries(reports)

        if args.list_json:
            payload = {
                "ticker": ticker,
                "company_name": company_name,
                "edisclosure_id": company_id,
                "reports": [r.to_dict() for r in reports],
            }
            # Накапливаем в список на уровне main — см. ниже
            list_json_rows.append(payload)
        elif args.dry_run:
            if reports:
                print(f"\n{ticker} ({company_name})  [id={company_id}]:")
                for r in sorted(
                    reports, key=lambda x: (x.fiscal_year, x.interim_rank), reverse=True
                ):
                    pdf_p = REPORTS_BASE_DIR / ticker / f"{ticker}_{r.period_key}.pdf"
                    status = "✓ PDF есть" if pdf_p.exists() else "→ будет скачан"
                    print(
                        f"  {r.period_key:10}  {status}  {r.file_label}  {r.file_url}"
                    )
            else:
                print(f"\n{ticker}: отчёты не найдены.")
        else:
            result = download_reports(ticker, reports)
            total_downloaded += len(result)
            total_skipped += max(0, len(reports) - len(result))

        # Пауза между компаниями (кроме последней); list-json тоже ходит на сайт
        if idx < len(companies_to_process) and (args.list_json or not args.dry_run):
            delay = random.uniform(COMPANY_DELAY_MIN, COMPANY_DELAY_MAX)
            logger.info("Пауза %.0f с перед следующей компанией...", delay)
            time.sleep(delay)

    if args.list_json:
        print(json.dumps(list_json_rows, ensure_ascii=False, indent=2))
        return

    if not args.dry_run:
        logger.info("=" * 60)
        logger.info(
            "Готово. Загружено/найдено PDF: %d, пропущено/ошибок: %d.",
            total_downloaded,
            total_skipped,
        )


if __name__ == "__main__":
    main()
