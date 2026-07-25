"""Слой ИИ-извлечения: единицы, страховки над ответом модели, отбор страниц.

Проверяется не качество распознавания (это отдельная задача на эталонных
отчётах), а наша обработка ответа: пересчёт масштабов, инварианты по
дивидендам и то, что нужные разделы PDF доходят до модели.
"""
from unittest.mock import patch

from app.services.report_parser.extractor_service import (
    _auto_fix_money_units,
    _collect_sanity_warnings,
    _fetch_moex_shares_issued,
    _resolve_report_date,
    _sanitize_special_dividends,
    _sync_net_income_fields,
)
from app.services.report_parser.pdf_extractor import (
    SECTION_KEYWORDS,
    _find_matches,
    _prioritized_pages,
)
from app.services.report_parser.schemas import ExtractedReport, rescale_to_millions


def _extracted(**kw) -> ExtractedReport:
    base = {
        "fiscal_year": 2024,
        "units_scale": "millions",
        "revenue": 500_000,
        "net_income": 80_000,
        "net_income_reported": 100_000,
        "equity": 400_000,
        "total_assets": 900_000,
        "current_assets": 200_000,
        "current_liabilities": 150_000,
        "shares_outstanding": 2_000_000_000,
        "capex": 60_000,
        "depreciation_amortization": 50_000,
    }
    base.update(kw)
    return ExtractedReport.model_validate(base)


# ─── Пересчёт единиц ────────────────────────────────────────────────────────


def test_billions_are_converted_to_millions():
    """В отчёте «в млрд руб.» числа записаны как есть, масштаб применяем сами."""
    r = rescale_to_millions(
        _extracted(units_scale="billions", revenue=1_000, depreciation_amortization=120)
    )

    assert r.units_scale == "millions"
    assert r.revenue == 1_000_000
    assert r.depreciation_amortization == 120_000


def test_thousand_shares_are_converted_to_units():
    r = rescale_to_millions(
        _extracted(shares_units_scale="thousands", shares_outstanding=444_793)
    )

    assert r.shares_units_scale == "units"
    assert r.shares_outstanding == 444_793_000


def test_per_share_dividends_are_not_rescaled():
    """Дивиденд на акцию всегда в полных рублях, масштаб отчёта к нему не применяется."""
    r = rescale_to_millions(
        _extracted(
            units_scale="billions",
            dividends_paid=True,
            dividends_per_share=20,
            special_dividends_per_share=12,
        )
    )

    assert r.dividends_per_share == 20
    assert r.special_dividends_per_share == 12


def test_currency_labels_from_pdf_are_normalized():
    """Модель цепляет из шапки таблицы подпись «в млн руб.» — приводим к ISO."""
    assert _extracted(currency="руб.").currency == "RUB"
    assert _extracted(currency="₽").currency == "RUB"
    assert _extracted(currency="usd").currency == "USD"


def test_money_autofix_ignores_prose_billions_when_units_are_millions():
    """«Обесценение 93 млрд» в заметках — не единицы отчёта, ×1000 нельзя."""
    r = _extracted(
        units_scale="millions",
        revenue=4_420_565,
        extraction_notes=(
            "Единицы отчёта: миллионы российских рублей (млн руб.). "
            "Обесценение 93 млрд — да."
        ),
    )
    fixed, msg = _auto_fix_money_units(r)
    assert msg is None
    assert fixed.units_scale == "millions"


def test_money_autofix_applies_when_notes_claim_billions_as_units():
    r = _extracted(
        units_scale="millions",
        revenue=4_420,
        extraction_notes="Единицы отчёта: в миллиардах рублей.",
    )
    fixed, msg = _auto_fix_money_units(r)
    assert msg is not None
    assert fixed.units_scale == "billions"


def test_notes_returned_as_list_are_joined():
    """В json_object-режиме модель иногда отдаёт заметки списком пунктов."""
    r = _extracted(extraction_notes=["единицы: млн", "акции: средневзвешенные"])

    assert "единицы: млн" in r.extraction_notes
    assert "акции: средневзвешенные" in r.extraction_notes


# ─── Разовые дивиденды ──────────────────────────────────────────────────────


def test_special_part_kept_when_within_total():
    r = _extracted(
        dividends_paid=True, dividends_per_share=20,
        special_dividends_per_share=12, special_dividends_note="  доплата за 2021  ",
    )

    assert _sanitize_special_dividends(r) == (12.0, "доплата за 2021")


def test_special_part_clamped_to_total():
    """Модель приняла спецдивиденд за добавку к общей сумме — обрезаем."""
    r = _extracted(dividends_paid=True, dividends_per_share=20, special_dividends_per_share=25)

    value, _ = _sanitize_special_dividends(r)
    assert value == 20.0


def test_special_part_dropped_without_total():
    r = _extracted(dividends_paid=True, special_dividends_per_share=7)

    assert _sanitize_special_dividends(r) == (None, None)


def test_special_part_dropped_when_no_dividends_paid():
    r = _extracted(
        dividends_paid=False, dividends_per_share=20, special_dividends_per_share=7
    )

    assert _sanitize_special_dividends(r) == (None, None)


def test_long_note_is_truncated():
    r = _extracted(
        dividends_paid=True, dividends_per_share=20, special_dividends_per_share=5,
        special_dividends_note="причина " * 100,
    )

    _, note = _sanitize_special_dividends(r)
    assert len(note) <= 257  # 256 символов плюс многоточие
    assert note.endswith("…")


# ─── Предупреждения для аналитика ───────────────────────────────────────────


def _warnings_text(**kw) -> str:
    return "\n".join(_collect_sanity_warnings(_extracted(**kw)))


def test_missing_amortization_is_flagged():
    assert "depreciation_amortization" in _warnings_text(depreciation_amortization=None)


def test_amortization_present_is_not_flagged():
    assert "depreciation_amortization" not in _warnings_text()


def test_capex_far_above_amortization_is_flagged():
    """CAPEX 60 000 при амортизации 5 000 — вероятно, в CAPEX попала покупка бизнеса."""
    assert "CAPEX / D&A" in _warnings_text(depreciation_amortization=5_000)


def test_bank_is_not_asked_for_amortization():
    text = _warnings_text(report_type="bank", depreciation_amortization=None, revenue=500_000)
    assert "depreciation_amortization" not in text


def test_special_dividends_always_asked_to_verify():
    text = _warnings_text(
        dividends_paid=True, dividends_per_share=20, special_dividends_per_share=12
    )
    assert "Разовая часть дивидендов" in text


def test_suspiciously_small_share_count_is_flagged():
    assert "shares_outstanding" in _warnings_text(shares_outstanding=500_000)


def test_annual_report_date_is_always_year_end():
    """Годовой отчёт: 31.12 даже если модель вернула другую/пустую дату."""
    r = _extracted(fiscal_year=2024, report_date="2024-06-30", period_type="annual")
    assert _resolve_report_date(r, period_type="annual", fiscal_year=2024) == "2024-12-31"
    r2 = _extracted(fiscal_year=2023, report_date=None, period_type="annual")
    assert _resolve_report_date(r2, period_type="ANNUAL") == "2023-12-31"


def test_llm_russian_filing_date_is_normalized_to_iso():
    """Ошибка LNZL: filing_date «30.04.2021» ломал strptime('%Y-%m-%d')."""
    from app.utils.date_parse import normalize_date_str, parse_date

    assert normalize_date_str("30.04.2021") == "2021-04-30"
    assert parse_date("30.04.2021") == __import__("datetime").date(2021, 4, 30)
    r = ExtractedReport.model_validate({
        "fiscal_year": 2020,
        "period_type": "annual",
        "currency": "RUB",
        "units_scale": "millions",
        "dividends_paid": False,
        "filing_date": "30.04.2021",
    })
    assert r.filing_date == "2021-04-30"


def test_llm_float_shares_are_coerced_to_int():
    """Ошибка MVID: shares_outstanding=178.38 (float) ломал валидацию int."""
    r = ExtractedReport.model_validate({
        "fiscal_year": 2024,
        "period_type": "annual",
        "currency": "RUB",
        "units_scale": "millions",
        "dividends_paid": False,
        "shares_outstanding": 178.38,
        "shares_units_scale": "millions",
    })
    assert r.shares_outstanding == 178
    r2 = rescale_to_millions(r)
    assert r2.shares_outstanding == 178_000_000


def test_net_income_fields_are_synced_when_one_missing():
    """Модель часто заполняет только одно поле прибыли — дозаполняем второе."""
    only_reported = _extracted(net_income=None, net_income_reported=-78_552)
    synced, msg = _sync_net_income_fields(only_reported)
    assert synced.net_income == -78_552
    assert synced.net_income_reported == -78_552
    assert msg and "net_income скопирован" in msg

    only_ni = _extracted(net_income=-78_552, net_income_reported=None)
    synced2, msg2 = _sync_net_income_fields(only_ni)
    assert synced2.net_income_reported == -78_552
    assert msg2 and "net_income_reported скопирован" in msg2


def test_moex_shares_issued_uses_issuesize():
    with patch(
        "app.services.report_parser.extractor_service.get_moex_issuesize",
        return_value={"issuesize": 6_906_575_210, "ticker": "AFLT"},
    ):
        assert _fetch_moex_shares_issued("AFLT") == 6_906_575_210
    with patch(
        "app.services.report_parser.extractor_service.get_moex_issuesize",
        return_value=None,
    ):
        assert _fetch_moex_shares_issued("XXXX") is None


def test_units_mismatch_between_fields_is_flagged():
    """Прибыль больше выручки — почти всегда разные единицы у разных полей."""
    assert "ИНВАРИАНТ НАРУШЕН" in _warnings_text(revenue=1_000, net_income=80_000)


# ─── Отбор страниц PDF ──────────────────────────────────────────────────────


def test_amortization_and_dividend_notes_are_recognized():
    text = (
        "отчет о движении денежных средств износ и амортизация 45 000 "
        "погашение кредитов и займов 12 000"
    )
    phrases, _ = _find_matches(text)

    assert "износ и амортизация" in phrases
    assert "погашение кредитов и займов" in phrases

    phrases, _ = _find_matches("примечание 25 специальный дивиденд 12 руб.")
    assert "специальный дивиденд" in phrases


def test_overflow_keeps_one_page_per_section():
    """При переполнении лимита нельзя терять целый раздел.

    Балансовые страницы всегда собирают больше совпадений (десяток строк
    «Итого …»), поэтому раньше страница с амортизацией вылетала из контекста
    именно на толстых отчётах.
    """
    balance_phrases = ["итого активы", "итого обязательства", "итого капитал", "total assets"]
    matched = {
        1: balance_phrases,
        2: balance_phrases[:3],
        3: balance_phrases[:2],
        9: ["износ и амортизация"],
    }
    hits = {1: {8: 4}, 2: {8: 3}, 3: {8: 2}, 9: {6: 1}}

    chosen = _prioritized_pages(matched, hits, limit=2)

    assert 9 in chosen
    assert len(chosen) == 2


def test_prioritized_pages_respects_limit_and_dedupes():
    matched = {i: ["итого активы"] for i in range(10)}
    hits = {i: {8: 1} for i in range(10)}

    chosen = _prioritized_pages(matched, hits, limit=3)

    assert len(chosen) == 3
    assert len(set(chosen)) == 3


def test_keyword_groups_are_not_empty():
    """Пустая группа сломала бы распределение квоты страниц по разделам."""
    assert all(len(group) > 0 for group in SECTION_KEYWORDS)
