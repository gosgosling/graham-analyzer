"""Оценка рынка по годам: P/E как у индекса и премия к ОФЗ."""

from app.services.analysis.market_overview import _aggregate


def test_pe_рынка_считается_с_убыточными_как_у_индекса():
    # (капитализация, прибыль, капитал, P/E, див. доходность)
    rows = [
        (1000.0, 200.0, 2000.0, 5.0, 10.0),
        (500.0, -100.0, 400.0, None, 0.0),  # убыток уменьшает прибыль рынка
        (300.0, 30.0, 300.0, 10.0, 5.0),
    ]
    agg = _aggregate(rows)
    assert agg["pe"] == round(1800 / 130, 2)
    assert agg["earnings_yield"] == round(130 / 1800 * 100, 2)
    # Медиана — только по прибыльным: 5 и 10.
    assert agg["pe_median"] == 7.5
    assert agg["companies"] == 3


def test_без_прибыли_рынка_оценки_нет():
    assert _aggregate([(1000.0, -50.0, 500.0, None, 0.0)]) is None
