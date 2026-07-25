#!/usr/bin/env python3
"""Живой прогон эталонных PDF через LLM → сравнение с golden-фикстурами.

Не валится на первой ошибке: по каждому PDF пишет score и проблемные поля.
Результат — JSON + текстовая сводка в tests/fixtures/golden/live_*.

Запуск из backend:
  GOLDEN_PDF_DIR=/tmp/golden_pdfs venv/bin/python scripts/run_live_extraction_quality.py
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.services.report_parser.extractor_service import (  # noqa: E402
    _auto_fix_money_units,
    _auto_fix_shares_units,
    compute_report_diff,
)
from app.services.report_parser.llm_client import extract_report_via_llm  # noqa: E402
from app.services.report_parser.pdf_extractor import extract_financial_pages  # noqa: E402
from app.services.report_parser.prompts import (  # noqa: E402
    build_system_prompt,
    build_user_prompt,
)
from app.services.report_parser.schemas import rescale_to_millions  # noqa: E402
from tests.test_extraction_quality import (  # noqa: E402
    _as_existing,
    _as_extracted,
    _load_golden,
    _load_index,
    _score,
    _status_map,
)


def main() -> int:
    pdf_dir = Path(os.environ.get("GOLDEN_PDF_DIR", "/tmp/golden_pdfs"))
    if not pdf_dir.is_dir():
        print(f"ERROR: GOLDEN_PDF_DIR={pdf_dir} не существует", file=sys.stderr)
        return 2
    if not settings.llm_configured:
        print("ERROR: LLM не настроен", file=sys.stderr)
        return 2

    out_dir = ROOT / "tests" / "fixtures" / "golden"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = out_dir / f"live_report_{stamp}.json"
    text_path = out_dir / f"live_report_{stamp}.txt"

    ticker_filter = {
        t.strip().upper()
        for t in os.environ.get("GOLDEN_TICKERS", "").split(",")
        if t.strip()
    }
    year_filter = {
        int(y.strip())
        for y in os.environ.get("GOLDEN_YEARS", "").split(",")
        if y.strip().isdigit()
    }

    print(f"model={settings.extraction_model_label}")
    print(f"base_url={settings.LLM_BASE_URL}")
    print(f"pdf_dir={pdf_dir}")
    if ticker_filter:
        print(f"tickers={','.join(sorted(ticker_filter))}")
    if year_filter:
        print(f"years={','.join(str(y) for y in sorted(year_filter))}")
    print("---")

    rows = []
    for item in _load_index():
        if ticker_filter and item["ticker"].upper() not in ticker_filter:
            continue
        if year_filter and int(item["year"]) not in year_filter:
            continue
        pdf_path = pdf_dir / f"{item['ticker']}_{item['year']}.pdf"
        if not pdf_path.exists():
            alts = list(pdf_dir.glob(f"{item['ticker']}*{item['year']}*.pdf"))
            pdf_path = alts[0] if alts else None
        if pdf_path is None:
            print(f"SKIP {item['ticker']} {item['year']}: PDF не найден")
            rows.append({**item, "status": "no_pdf"})
            continue

        print(f"RUN  {item['ticker']} {item['year']} ← {pdf_path.name} …", flush=True)
        golden = _load_golden(item["file"])
        try:
            extraction = extract_financial_pages(pdf_path, pdf_label=pdf_path.name)
            extracted = extract_report_via_llm(
                system_prompt=build_system_prompt("general"),
                user_prompt=build_user_prompt(
                    ticker=item["ticker"],
                    expected_year=item["year"],
                    company_name=golden.get("name") or item["ticker"],
                    sector=golden.get("sector"),
                    pdf_text=extraction.text,
                    is_scanned=extraction.is_scanned,
                ),
                images=extraction.page_images if extraction.is_scanned else None,
            )
            extracted, money_msg = _auto_fix_money_units(extracted)
            extracted, shares_msg = _auto_fix_shares_units(extracted)
            extracted = rescale_to_millions(extracted)

            diffs, summary = compute_report_diff(
                _as_existing(golden), extracted, report_type="general"
            )
            score = _score(summary)
            bad = [
                {
                    "field": d.field,
                    "status": d.status,
                    "existing": d.existing_value,
                    "extracted": d.extracted_value,
                    "pct_diff": d.pct_diff,
                }
                for d in diffs
                if d.status in {"mismatch", "missing_ai"}
            ]
            row = {
                **item,
                "status": "ok",
                "score": round(score, 4),
                "matched": summary.matched,
                "close": summary.close,
                "mismatched": summary.mismatched,
                "missing_in_ai": summary.missing_in_ai,
                "missing_in_existing": summary.missing_in_existing,
                "both_missing": summary.both_missing,
                "selected_pages": len(extraction.selected_pages),
                "total_pages": extraction.total_pages,
                "auto_fix_money": money_msg,
                "auto_fix_shares": shares_msg,
                "bad_fields": bad,
                "extracted": extracted.model_dump(mode="json"),
            }
            print(
                f"  → score={score:.0%} match={summary.matched} close={summary.close} "
                f"mismatch={summary.mismatched} missing_ai={summary.missing_in_ai}"
            )
            if bad:
                print("  bad:", ", ".join(f"{b['field']}:{b['status']}" for b in bad[:10]))
        except Exception as exc:  # noqa: BLE001
            print(f"  → FAIL: {type(exc).__name__}: {exc}")
            row = {
                **item,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-1500:],
            }
        rows.append(row)

    ok_scores = [r["score"] for r in rows if r.get("status") == "ok"]
    payload = {
        "model": settings.extraction_model_label,
        "base_url": settings.LLM_BASE_URL,
        "pdf_dir": str(pdf_dir),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "n_ok": len(ok_scores),
        "n_error": sum(1 for r in rows if r.get("status") == "error"),
        "mean_score": round(sum(ok_scores) / len(ok_scores), 4) if ok_scores else None,
        "min_score": min(ok_scores) if ok_scores else None,
        "results": rows,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"model: {payload['model']}",
        f"ok: {payload['n_ok']}  errors: {payload['n_error']}",
        f"mean_score: {payload['mean_score']}  min_score: {payload['min_score']}",
        "",
    ]
    for r in rows:
        if r.get("status") == "ok":
            bad = ", ".join(
                f"{b['field']}:{b['status']}" for b in r.get("bad_fields", [])[:12]
            ) or "—"
            lines.append(
                f"{r['ticker']} {r['year']}: score={r['score']:.0%} "
                f"match={r['matched']} close={r['close']} "
                f"mismatch={r['mismatched']} missing_ai={r['missing_in_ai']} | {bad}"
            )
        else:
            lines.append(f"{r['ticker']} {r['year']}: {r.get('status')} {r.get('error','')}")
    text = "\n".join(lines) + "\n"
    text_path.write_text(text, encoding="utf-8")
    print("---")
    print(text)
    print(f"JSON → {report_path}")
    print(f"TXT  → {text_path}")
    return 0 if ok_scores else 1


if __name__ == "__main__":
    raise SystemExit(main())
