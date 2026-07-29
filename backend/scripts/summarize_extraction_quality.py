#!/usr/bin/env python3
"""Сводка качества извлечения: поле → доля совпадений по годам.

`run_live_extraction_quality.py` даёт score на отчёт: «LKOH 2023 — 81%». Для
правок промпта нужен разворот той же матрицы — по полям: не «какой отчёт хуже»,
а «какое поле модель стабильно портит и в каких годах».

Скрипт не ходит ни в LLM, ни в базу. Ответы модели уже сохранены в
`live_report_*.json` (поле `extracted`), эталоны лежат рядом в фикстурах —
сравнение считается заново теми же `compute_report_diff`, что и в живом прогоне.
Поэтому его можно гонять сколько угодно раз и после правок порогов сравнения.

Если один и тот же отчёт прогонялся несколько раз (правки промпта, смена
модели), по умолчанию берётся последний прогон — иначе старые провалы навсегда
портят статистику. `--all-runs` показывает каждый прогон отдельно.

Запуск из backend:
  venv/bin/python scripts/summarize_extraction_quality.py
  venv/bin/python scripts/summarize_extraction_quality.py --out ../docs/EXTRACTION-FIELD-MATRIX.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.report_parser.extractor_service import (  # noqa: E402
    _COMPARABLE_FIELDS,
    compute_report_diff,
)
from app.services.report_parser.schemas import ExtractedReport  # noqa: E402
from tests.test_extraction_quality import _as_existing, _load_golden  # noqa: E402

# Статусы, при которых эталон заполнен, то есть поле участвует в доле совпадений.
# missing_existing / both_missing означают «сверять не с чем» — это дыра в
# эталоне, а не ошибка модели, и в знаменатель она не попадает.
_SCORED_STATUSES = ("match", "close", "mismatch", "missing_ai")
_GOOD_STATUSES = ("match", "close")

_SYMBOL = {
    "match": "✓",
    "close": "≈",
    "mismatch": "✗",
    "missing_ai": "∅",
    "missing_existing": "·",
    "both_missing": "·",
}


@dataclass
class ReportRun:
    """Один отчёт в одном прогоне: какие статусы получились по полям."""
    ticker: str
    year: int
    model: str
    stamp: str
    statuses: Dict[str, str]

    @property
    def key(self) -> Tuple[str, int]:
        return (self.ticker, self.year)

    @property
    def label(self) -> str:
        return f"{self.ticker} {self.year}"


def _label_by_field() -> Dict[str, str]:
    return {spec.key: spec.label for spec in _COMPARABLE_FIELDS}


def _scored_fields(report_type: str) -> List[str]:
    return [
        spec.key
        for spec in _COMPARABLE_FIELDS
        if spec.scored and report_type in spec.relevant_for
    ]


def _load_runs(golden_dir: Path, model_filter: Optional[str]) -> List[ReportRun]:
    """Пересчитать diff по сохранённым ответам модели из всех живых прогонов."""
    runs: List[ReportRun] = []
    for path in sorted(golden_dir.glob("live_report_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = payload.get("model") or "?"
        if model_filter and model_filter.lower() not in model.lower():
            continue
        stamp = path.stem.replace("live_report_", "")
        for row in payload.get("results", []):
            if row.get("status") != "ok" or not row.get("extracted"):
                continue
            golden = _load_golden(row["file"])
            extracted = ExtractedReport.model_validate(row["extracted"])
            report_type = row["extracted"].get("report_type") or "general"
            diffs, _ = compute_report_diff(
                _as_existing(golden), extracted, report_type=report_type
            )
            runs.append(
                ReportRun(
                    ticker=row["ticker"],
                    year=int(row["year"]),
                    model=model,
                    stamp=stamp,
                    statuses={d.field: d.status for d in diffs},
                )
            )
    return runs


def _keep_latest(runs: List[ReportRun]) -> List[ReportRun]:
    """Последний прогон каждого отчёта: файлы отсортированы по времени в имени."""
    latest: Dict[Tuple[str, int], ReportRun] = {}
    for run in runs:
        latest[run.key] = run
    return sorted(latest.values(), key=lambda r: (r.ticker, r.year))


def _share(good: int, scored: int) -> str:
    if scored == 0:
        return "—"
    return f"{good}/{scored} ({good / scored:.0%})"


def _by_year_table(runs: List[ReportRun], fields: List[str]) -> List[str]:
    """Главная таблица плана: поле → доля совпадений по годам."""
    years = sorted({run.year for run in runs})
    labels = _label_by_field()

    counts: Dict[Tuple[str, int], List[int]] = defaultdict(lambda: [0, 0])  # good, scored
    totals: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for run in runs:
        for field in fields:
            status = run.statuses.get(field)
            if status not in _SCORED_STATUSES:
                continue
            good = 1 if status in _GOOD_STATUSES else 0
            cell = counts[(field, run.year)]
            cell[0] += good
            cell[1] += 1
            total = totals[field]
            total[0] += good
            total[1] += 1

    lines = [
        "| Поле | " + " | ".join(str(y) for y in years) + " | Всего |",
        "| --- |" + " --- |" * (len(years) + 1),
    ]
    ordered = sorted(
        fields,
        key=lambda f: (
            totals[f][0] / totals[f][1] if totals[f][1] else 2.0,  # худшие сверху
            f,
        ),
    )
    for field in ordered:
        if totals[field][1] == 0:
            continue
        cells = [_share(*counts[(field, y)]) for y in years]
        lines.append(
            f"| `{field}` — {labels.get(field, '')} | "
            + " | ".join(cells)
            + f" | **{_share(*totals[field])}** |"
        )
    return lines


def _detail_table(runs: List[ReportRun], fields: List[str]) -> List[str]:
    """Матрица поле × отчёт: видно, единичный это сбой или системный."""
    labels = _label_by_field()
    header = [run.label for run in runs]
    lines = [
        "| Поле | " + " | ".join(header) + " |",
        "| --- |" + " --- |" * len(header),
    ]
    for field in fields:
        cells = [_SYMBOL.get(run.statuses.get(field, ""), " ") for run in runs]
        if all(c == "·" for c in cells):
            continue
        lines.append(
            f"| `{field}` — {labels.get(field, '')} | " + " | ".join(cells) + " |"
        )
    lines.append("")
    lines.append("✓ совпало · ≈ расхождение <1% · ✗ расхождение · ∅ модель не нашла · · нет эталона")
    return lines


def _provenance(runs: List[ReportRun]) -> List[str]:
    """Из какого прогона взят каждый отчёт — иначе цифры не воспроизвести."""
    by_run: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for run in runs:
        by_run[(run.stamp, run.model)].append(run.label)
    return [
        f"- `live_report_{stamp}.json` ({model}): {', '.join(sorted(labels))}"
        for (stamp, model), labels in sorted(by_run.items())
    ]


def _problem_list(runs: List[ReportRun], fields: List[str]) -> List[str]:
    """Поля, которые модель портит чаще всего, с указанием отчётов."""
    bad: Dict[str, List[str]] = defaultdict(list)
    for run in runs:
        for field in fields:
            if run.statuses.get(field) in ("mismatch", "missing_ai"):
                mark = "∅" if run.statuses[field] == "missing_ai" else "✗"
                bad[field].append(f"{run.label}{mark}")
    lines = []
    for field, reports in sorted(bad.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- `{field}` — {len(reports)}: {', '.join(reports)}")
    return lines or ["- пусто: все поля совпали"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=str(ROOT / "tests" / "fixtures" / "golden"),
        help="каталог с live_report_*.json и эталонами",
    )
    parser.add_argument("--out", help="записать отчёт в markdown-файл")
    parser.add_argument("--model", help="учитывать только прогоны этой модели")
    parser.add_argument(
        "--all-runs",
        action="store_true",
        help="не схлопывать повторные прогоны одного отчёта до последнего",
    )
    parser.add_argument(
        "--report-type",
        default="general",
        choices=("general", "bank"),
        help="набор полей: general или bank",
    )
    args = parser.parse_args()

    golden_dir = Path(args.dir)
    if not golden_dir.is_dir():
        print(f"ERROR: нет каталога {golden_dir}", file=sys.stderr)
        return 2

    runs = _load_runs(golden_dir, args.model)
    if not runs:
        print("ERROR: не найдено ни одного live_report_*.json с результатами", file=sys.stderr)
        return 2
    if not args.all_runs:
        runs = _keep_latest(runs)

    fields = _scored_fields(args.report_type)
    models = sorted({run.model for run in runs})

    lines: List[str] = [
        "# Качество извлечения: поле → доля совпадений",
        "",
        f"Отчётов в выборке: **{len(runs)}** "
        f"({', '.join(sorted({r.ticker for r in runs}))}). "
        f"Модель: {', '.join(models)}.",
        "",
        "Доля = (совпало + расхождение <1%) / поля, где эталон заполнен.",
        "",
        "## По годам",
        "",
        *_by_year_table(runs, fields),
        "",
        "## По отчётам",
        "",
        *_detail_table(runs, fields),
        "",
        "## Что чинить в первую очередь",
        "",
        *_problem_list(runs, fields),
        "",
        "## Откуда взяты цифры",
        "",
        *_provenance(runs),
        "",
    ]
    text = "\n".join(lines)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(text + "\n", encoding="utf-8")
        print(f"\n→ {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
