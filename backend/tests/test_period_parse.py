"""Unit-тесты разбора периодов e-disclosure (offline).

Модули скрапера подключает `ensure_scraper_importable` — та же функция, что и
в рабочем коде. Раньше тест повторял вставку в `sys.path` своей формулой пути,
и при переносе каталогов ломался отдельно от приложения.
"""
import pytest

from app.services.disclosure.edisclosure_client import ensure_scraper_importable

ensure_scraper_importable()

from period_parse import filter_coverage_entries, parse_period_label  # noqa: E402


@pytest.mark.parametrize(
    "label,ptype,year,quarter,key",
    [
        ("2024", "annual", 2024, None, "2024"),
        ("2026, 3 месяца", "quarterly", 2026, 1, "2026_Q1"),
        ("2026, 1 квартал", "quarterly", 2026, 1, "2026_Q1"),
        ("2025, 6 месяцев", "semi_annual", 2025, None, "2025_H1"),
        ("2025, 9 месяцев", "quarterly", 2025, 3, "2025_Q3"),
        ("2024, 12 месяцев", "annual", 2024, None, "2024"),
    ],
)
def test_parse_period_label(label, ptype, year, quarter, key):
    p = parse_period_label(label)
    assert p is not None
    assert p.period_type == ptype
    assert p.fiscal_year == year
    assert p.fiscal_quarter == quarter
    assert p.period_key == key


def test_filter_coverage_latest_interim_only():
    class E:
        def __init__(self, period_type, fiscal_year, interim_rank, fiscal_quarter=None):
            self.period_type = period_type
            self.fiscal_year = fiscal_year
            self.interim_rank = interim_rank
            self.fiscal_quarter = fiscal_quarter

    entries = [
        E("annual", 2023, 0),
        E("annual", 2024, 0),
        E("quarterly", 2025, 1, 1),
        E("semi_annual", 2025, 2),
        E("quarterly", 2026, 1, 1),
        E("annual", 2009, 0),  # ниже min year
    ]
    kept = filter_coverage_entries(entries, min_annual_year=2010)
    keys = {(e.period_type, e.fiscal_year, e.fiscal_quarter) for e in kept}
    assert ("annual", 2023, None) in keys
    assert ("annual", 2024, None) in keys
    assert ("annual", 2009, None) not in keys
    # latest interim = 2026 Q1
    assert ("quarterly", 2026, 1) in keys
    assert ("semi_annual", 2025, None) not in keys
