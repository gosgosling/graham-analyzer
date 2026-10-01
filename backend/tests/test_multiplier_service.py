

def test_сравнительная_колонка_подменяет_прошлое_полугодие_в_ltm():
    """LTM по свежему отчёту вычитает прошлый период из ЕГО сравнительной колонки.

    ЛУКОЙЛ: в августе 2025-го за 1П2025 опубликовано 287 023, а в отчёте за
    1П2026 то же полугодие показано уже без деконсолидированных активов —
    90 296. Строка 1П2025 хранит опубликованное тогда; LTM на август 2026-го
    обязан вычесть сопоставимое, иначе смешает периметры.
    """
    from types import SimpleNamespace

    from app.services.analysis.multiplier_service import comparative_prior, _field_rub

    current = SimpleNamespace(comparative={"net_income_reported": 90296.0},
                              currency="RUB", exchange_rate=None, fiscal_year=2026)
    published = SimpleNamespace(net_income_reported=287023.0, capex=386630.0,
                                currency="RUB", exchange_rate=None)

    view = comparative_prior(current, published)
    assert _field_rub(view, "net_income_reported") == 90296.0
    # Чего в колонке нет, то читается из строки прошлого периода.
    assert _field_rub(view, "capex") == 386630.0

    # Нет колонки — всё как прежде.
    plain = SimpleNamespace(comparative=None)
    assert comparative_prior(plain, published) is published


def test_сравнительная_колонка_работает_и_без_строки_прошлого_периода():
    from types import SimpleNamespace

    from app.services.analysis.multiplier_service import comparative_prior, _field_rub

    current = SimpleNamespace(comparative={"revenue": 100.0}, currency="RUB",
                              exchange_rate=None, fiscal_year=2026)
    view = comparative_prior(current, None)
    assert _field_rub(view, "revenue") == 100.0
    assert view.capex is None
    assert view.fiscal_year == 2025
