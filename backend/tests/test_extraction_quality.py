"""Качество извлечения: сравнение AI-ответа с эталонными отчётами.

Эталоны — вручную заполненные и verified отчёты ЛУКОЙЛа (LKOH) и НОВАТЭКа
(NVTK), выгруженные из БД в `tests/fixtures/golden/`.

Два уровня:

1. **Всегда** — `compute_report_diff` на фикстурах: идеальное совпадение,
   типичные ошибки модели (тысячи акций, заголовок вместо «Итого»), сводка.
   LLM и PDF не нужны.

2. **Опционально** — живой прогон через LLM (`pytest -m live_extraction`),
   если заданы `GOLDEN_PDF_DIR` и настроен LLM. Это уже метрика качества
   парсинга на реальных PDF; без PDF тесты пропускаются.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.report_parser.extractor_service import compute_report_diff
from app.services.report_parser.schemas import ExtractedReport

FIXTURES = Path(__file__).parent / "fixtures" / "golden"
INDEX_PATH = FIXTURES / "index.json"

# Поля, по которым сравниваем эталон с «ответом модели».
# Даты и акции реестра — вне LLM (31.12 / auditor optional / MOEX) и в score
# не входят (см. scored=False в extractor_service._COMPARABLE_FIELDS).
_COMPARE_KEYS = (
    "currency",
    "revenue", "net_income", "net_income_reported",
    "total_assets", "current_assets", "total_liabilities", "current_liabilities",
    "equity", "cash_and_equivalents", "debt",
    "dividends_per_share", "dividends_paid", "special_dividends_per_share",
    "operating_cash_flow", "capex", "lease_principal", "lease_interest",
    "interest_paid", "depreciation_amortization",
)


def _load_index() -> list[dict]:
    assert INDEX_PATH.exists(), (
        f"Нет {INDEX_PATH}. Выгрузите эталоны: "
        f"venv/bin/python scripts/export_golden_reports.py"
    )
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _load_golden(filename: str) -> dict[str, Any]:
    return json.loads((FIXTURES / filename).read_text(encoding="utf-8"))


def _as_existing(golden: dict) -> SimpleNamespace:
    """Эталонный отчёт как объект с атрибутами (вместо ORM-модели)."""
    data = {k: golden.get(k) for k in _COMPARE_KEYS}
    return SimpleNamespace(**data)


def _as_extracted(golden: dict, **overrides) -> ExtractedReport:
    """Собрать ExtractedReport из эталона (+ намеренные ошибки модели)."""
    payload = {
        "fiscal_year": golden["fiscal_year"],
        "period_type": "annual",
        "accounting_standard": "IFRS",
        "consolidated": True,
        "report_type": "general",
        "currency": golden.get("currency") or "RUB",
        "units_scale": "millions",
        "shares_units_scale": "units",
        "dividends_paid": bool(golden.get("dividends_paid")),
    }
    for key in _COMPARE_KEYS:
        if key in ("dividends_paid",):
            continue
        payload[key] = golden.get(key)
    payload.update(overrides)
    return ExtractedReport.model_validate(payload)


def _status_map(diffs) -> dict[str, str]:
    return {d.field: d.status for d in diffs}


def _score(summary) -> float:
    """Доля совпавших+близких среди полей, где эталон заполнен."""
    scored = summary.matched + summary.close + summary.mismatched + summary.missing_in_ai
    if scored == 0:
        return 0.0
    return (summary.matched + summary.close) / scored


# ─── Фикстуры на месте ──────────────────────────────────────────────────────


def test_golden_index_is_present_and_complete():
    index = _load_index()
    tickers = {item["ticker"] for item in index}
    assert "LKOH" in tickers
    assert "NVTK" in tickers
    for item in index:
        path = FIXTURES / item["file"]
        assert path.exists(), path
        data = _load_golden(item["file"])
        assert data["verified_by_analyst"] is True
        assert data["revenue"] is not None
        assert data["equity"] is not None


@pytest.mark.parametrize("item", _load_index(), ids=lambda i: f"{i['ticker']}_{i['year']}")
def test_perfect_extraction_scores_100(item):
    """Если модель повторила эталон поле в поле — diff зелёный на 100%."""
    golden = _load_golden(item["file"])
    diffs, summary = compute_report_diff(
        _as_existing(golden), _as_extracted(golden), report_type="general"
    )

    assert summary.mismatched == 0, _status_map(diffs)
    assert summary.missing_in_ai == 0, _status_map(diffs)
    assert _score(summary) == 1.0
    assert summary.matched + summary.close + summary.both_missing + summary.missing_in_existing == summary.total_fields


# ─── Типичные ошибки модели — статусы должны ловиться ───────────────────────


def test_dates_and_shares_are_not_scored():
    """report_date / filing_date / акции — автополя, в score LLM не входят."""
    golden = _load_golden("LKOH_2024_IFRS_annual.json")
    extracted = _as_extracted(
        golden,
        report_date=None,
        filing_date=None,
        shares_outstanding=None,
    )
    diffs, _ = compute_report_diff(
        _as_existing(golden), extracted, report_type="general"
    )
    fields = {d.field for d in diffs}
    assert "report_date" not in fields
    assert "filing_date" not in fields
    assert "shares_outstanding" not in fields


def test_missing_amortization_is_missing_ai():
    golden = _load_golden("NVTK_2024_IFRS_annual.json")
    assert golden.get("depreciation_amortization") is not None

    extracted = _as_extracted(golden, depreciation_amortization=None)
    statuses = _status_map(
        compute_report_diff(_as_existing(golden), extracted, report_type="general")[0]
    )
    assert statuses["depreciation_amortization"] == "missing_ai"


def test_liabilities_taken_from_wrong_row_is_mismatch():
    """Типичная ошибка: взяли «Итого капитал и обязательства» вместо обязательств."""
    golden = _load_golden("LKOH_2023_IFRS_annual.json")
    wrong = (golden["total_liabilities"] or 0) + (golden["equity"] or 0)
    extracted = _as_extracted(golden, total_liabilities=wrong)

    statuses = _status_map(
        compute_report_diff(_as_existing(golden), extracted, report_type="general")[0]
    )
    assert statuses["total_liabilities"] == "mismatch"


def test_rounding_within_one_percent_is_close():
    golden = _load_golden("NVTK_2023_IFRS_annual.json")
    # 0.4% — внутри «close», но не «match» (порог match ≈ 0.5% и 1 млн)
    revenue = golden["revenue"]
    extracted = _as_extracted(golden, revenue=revenue * 1.004)

    statuses = _status_map(
        compute_report_diff(_as_existing(golden), extracted, report_type="general")[0]
    )
    assert statuses["revenue"] in {"close", "match"}


def test_score_drops_when_key_fields_wrong():
    golden = _load_golden("LKOH_2024_IFRS_annual.json")
    extracted = _as_extracted(
        golden,
        revenue=golden["revenue"] * 2,
        net_income=golden["net_income"] * 2,
        equity=None,
        depreciation_amortization=None,
    )
    _, summary = compute_report_diff(
        _as_existing(golden), extracted, report_type="general"
    )

    assert summary.mismatched >= 2
    assert summary.missing_in_ai >= 1
    assert _score(summary) < 0.9


def test_bank_fields_skipped_for_general_report():
    """Банковские поля не участвуют в diff промышленной компании."""
    golden = _load_golden("NVTK_2025_IFRS_annual.json")
    diffs, _ = compute_report_diff(
        _as_existing(golden), _as_extracted(golden), report_type="general"
    )
    fields = {d.field for d in diffs}
    assert "provisions" not in fields
    assert "net_interest_income" not in fields
    assert "depreciation_amortization" in fields


# ─── Живой прогон LLM (опционально) ─────────────────────────────────────────


@pytest.mark.live_extraction
def test_live_llm_against_golden_pdfs():
    """
    Прогнать реальные PDF через LLM и сравнить с эталонами.

    Требует:
      * настроенный LLM (LLM_* в окружении / .env);
      * каталог PDF: GOLDEN_PDF_DIR, файлы вида LKOH_2024.pdf, NVTK_2023.pdf;
      * порог качества EXTRACTION_MIN_SCORE (по умолчанию 0.70).

    Запуск:
      GOLDEN_PDF_DIR=/path/to/pdfs pytest -m live_extraction -v
    """
    pdf_dir = Path(os.environ.get("GOLDEN_PDF_DIR", ""))
    if not pdf_dir.is_dir():
        pytest.skip("GOLDEN_PDF_DIR не задан или каталог не существует")

    from app.config import settings
    if not settings.llm_configured:
        pytest.skip("LLM не настроен")

    from app.services.report_parser.pdf_extractor import extract_financial_pages
    from app.services.report_parser.prompts import build_system_prompt, build_user_prompt
    from app.services.report_parser.llm_client import extract_report_via_llm
    from app.services.report_parser.extractor_service import (
        _auto_fix_money_units,
        _auto_fix_shares_units,
    )
    from app.services.report_parser.schemas import rescale_to_millions

    min_score = float(os.environ.get("EXTRACTION_MIN_SCORE", "0.70"))
    results = []

    for item in _load_index():
        pdf_path = pdf_dir / f"{item['ticker']}_{item['year']}.pdf"
        if not pdf_path.exists():
            # допускаем и человекочитаемые имена
            alt = list(pdf_dir.glob(f"{item['ticker']}*{item['year']}*.pdf"))
            if not alt:
                continue
            pdf_path = alt[0]

        golden = _load_golden(item["file"])
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
        extracted, _ = _auto_fix_money_units(extracted)
        extracted, _ = _auto_fix_shares_units(extracted)
        extracted = rescale_to_millions(extracted)

        diffs, summary = compute_report_diff(
            _as_existing(golden), extracted, report_type="general"
        )
        score = _score(summary)
        results.append((item, score, summary, diffs))

    if not results:
        pytest.skip("В GOLDEN_PDF_DIR нет PDF под эталоны (LKOH_2024.pdf и т.п.)")

    lines = []
    for item, score, summary, diffs in results:
        bad = [d for d in diffs if d.status in {"mismatch", "missing_ai"}]
        bad_s = ", ".join(f"{d.field}:{d.status}" for d in bad[:8]) or "—"
        lines.append(
            f"{item['ticker']} {item['year']}: score={score:.0%} "
            f"match={summary.matched} close={summary.close} "
            f"mismatch={summary.mismatched} missing_ai={summary.missing_in_ai} "
            f"| {bad_s}"
        )
    report = "\n".join(lines)
    print("\n" + report)

    worst = min(score for _, score, _, _ in results)
    assert worst >= min_score, (
        f"Качество извлечения ниже порога {min_score:.0%}:\n{report}"
    )
