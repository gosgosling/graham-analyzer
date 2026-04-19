#!/usr/bin/env python3
"""
Сопоставление тикеров из БД с числовыми id эмитентов на www.e-disclosure.ru.

Шаги (как в инструкции на портале):
1. По тикеру запрашиваем у MOEX ISS ИНН и официальное название эмитента (emitters).
2. На e-disclosure выполняем поиск по ИНН через форму «Поиск по компаниям»
   (POST /poisk-po-kompaniyam), в сессии браузера (обход ServicePipe).
3. Из ссылок company.aspx?id=… извлекаем id.

Запуск (нужен установленный Chromium: playwright install chromium):

  cd tools/edisclosure-scraper && source ../../backend/venv/bin/activate
  python resolve_edisclosure_ids.py --output edisclosure_ids_generated.json

Дополнительно:
  --limit 20        только первые N компаний (тест)
  --skip-existing   не перезаписывать тикеры, уже есть в company_ids.json
  --moex-only       только выгрузить ИНН из MOEX в JSON (без e-disclosure)

Примечание: массовый автоматический опрос делайте с паузами; при ошибках проверьте тикер вручную.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path

from db_client import get_companies_full_from_db
from edisclosure_search import search_company_id_playwright
from moex_emitter import get_emitter_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

_MAPPING_FILE = Path(__file__).parent / "company_ids.json"


def load_existing_mapping() -> dict[str, int]:
    if not _MAPPING_FILE.exists():
        return {}
    raw = json.loads(_MAPPING_FILE.read_text(encoding="utf-8"))
    out: dict[str, int] = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(v.get("id"), int):
            out[k.upper()] = v["id"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Поиск e-disclosure id по тикерам из БД")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "edisclosure_ids_generated.json",
        help="Файл результата (JSON)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Ограничить число компаний (0 = все)")
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Пропускать тикеры, для которых уже задан id в company_ids.json",
    )
    ap.add_argument(
        "--moex-only",
        action="store_true",
        help="Только MOEX: ИНН/ОГРН/название, без запросов к e-disclosure",
    )
    ap.add_argument("--delay-min", type=float, default=2.0, help="Пауза между запросами к сайту (сек)")
    ap.add_argument("--delay-max", type=float, default=5.0, help="Верхняя граница паузы (сек)")
    args = ap.parse_args()

    existing = load_existing_mapping() if args.skip_existing else {}
    companies = get_companies_full_from_db()
    if args.limit and args.limit > 0:
        companies = companies[: args.limit]

    result: dict[str, dict] = {}

    for idx, c in enumerate(companies, start=1):
        t = c.ticker.upper()
        if args.skip_existing and t in existing:
            logger.info("[%d/%d] %s — уже в company_ids.json, пропуск.", idx, len(companies), t)
            continue

        logger.info("[%d/%d] MOEX: %s …", idx, len(companies), t)
        info = get_emitter_info(t)
        if not info:
            result[t] = {
                "id": None,
                "name": c.name,
                "inn": None,
                "ogrn": None,
                "moex_title": None,
                "error": "MOEX: инструмент не найден или нет EMITTER_ID",
            }
            continue

        inn = info.get("inn")
        ogrn = info.get("ogrn")
        title = info.get("title")

        row: dict = {
            "id": None,
            "name": title or c.name,
            "inn": inn,
            "ogrn": ogrn,
            "moex_title": title,
        }

        if args.moex_only:
            result[t] = row
            continue

        ed_id: int | None = None
        try:
            if inn:
                ed_id = search_company_id_playwright(str(inn), moex_title=title)
            if ed_id is None and title:
                time.sleep(random.uniform(args.delay_min, args.delay_max))
                q = (title[:120] if len(title) > 120 else title)
                ed_id = search_company_id_playwright(q, moex_title=title)
        except Exception as exc:
            logger.exception("e-disclosure: %s: %s", t, exc)
            row["error"] = str(exc)
            result[t] = row
            time.sleep(random.uniform(args.delay_min, args.delay_max))
            continue

        row["id"] = ed_id
        if ed_id is None:
            row["error"] = "Поиск e-disclosure не вернул company.aspx?id="
        result[t] = row
        logger.info("[%s] e-disclosure id=%s inn=%s", t, ed_id, inn)

        time.sleep(random.uniform(args.delay_min, args.delay_max))

    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Записано %d записей в %s", len(result), args.output)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
