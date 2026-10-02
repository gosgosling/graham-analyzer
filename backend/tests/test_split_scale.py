"""Шкала цен у дробления: как торговалось или уже пересчитано."""
from datetime import date, timedelta

from app.services.market.split_scale import (
    ADJUSTED, RAW, classify, repair_rows, scale_at_split, to_traded, unexplained_jumps,
)

SPLIT = [{"date": "2026-04-17", "ratio": 10}]
DAY = date(2026, 4, 17)


def days(start: date, n: int, price: float, step: float = 0.0):
    return [(start + timedelta(days=i), price + step * i) for i in range(n)]


def test_отношение_цен_на_границе_определяет_шкалу():
    assert classify(10.2, 10) == RAW
    assert classify(0.98, 10) == ADJUSTED
    assert classify(3.0, 10) is None  # ни то ни другое — не трогаем


def test_мосбиржа_пересчитала_ряд_как_у_т():
    moex = days(date(2026, 3, 1), 41, 330.0, -0.3) + days(DAY, 30, 326.0)
    assert scale_at_split(moex, DAY, 10) == ADJUSTED
    raw = [(d, p * 10) for d, p in moex if d < DAY] + [(d, p) for d, p in moex if d >= DAY]
    assert scale_at_split(raw, DAY, 10) == RAW


def test_ремонт_смеси_источников_и_повторный_запуск():
    # Мосбиржа: до дробления уже в новой шкале. T-Invest: три дня как торговались.
    rows = [(d, p, "moex") for d, p in days(date(2026, 3, 1), 41, 330.0, -0.3)]
    rows += [(date(2026, 3, 21), 3337.8, "tinvest"), (date(2026, 4, 5), 3213.8, "tinvest"),
             (date(2026, 4, 11), 3196.0, "tinvest")]
    rows += [(d, p, "moex") for d, p in days(DAY, 30, 326.0)]
    rows.sort()
    factors = repair_rows(rows, SPLIT)
    fixed = [(d, p * factors.get(i, 1.0), s) for i, (d, p, s) in enumerate(rows)]
    # Исправлены все мосбиржевые дни до дробления — и только они.
    assert {rows[i][2] for i in factors} == {"moex"}
    assert all(rows[i][0] < DAY for i in factors)
    assert all(abs(f - 10) < 1e-9 for f in factors.values())
    # Ряд стал непрерывным в шкале «как торговалось»: скачок только в день дробления.
    assert unexplained_jumps([(d, p) for d, p, _ in fixed], SPLIT) == []
    # Второй прогон ничего не меняет.
    assert repair_rows(fixed, SPLIT) == {}


def test_ряд_как_торговался_не_трогается():
    rows = [(d, p * 10, "moex") for d, p in days(date(2026, 3, 1), 41, 330.0)]
    rows += [(d, p, "moex") for d, p in days(DAY, 30, 326.0)]
    assert repair_rows(rows, SPLIT) == {}


def test_цена_на_дату_возвращается_к_торговавшейся():
    assert to_traded(319.6, date(2026, 4, 10), SPLIT, lambda e: True) == 3196.0
    assert to_traded(326.26, date(2026, 4, 17), SPLIT, lambda e: True) == 326.26  # после — не трогаем
    assert to_traded(3196.0, date(2026, 4, 10), SPLIT, lambda e: False) == 3196.0  # источник не пересчитан


def test_скачок_без_записанного_дробления_виден_аудиту():
    pts = days(date(2026, 3, 1), 10, 100.0) + days(date(2026, 3, 11), 10, 12.5)
    assert unexplained_jumps(pts, []) == [(date(2026, 3, 11), 0.125)]
    assert unexplained_jumps(pts, [{"date": "2026-03-11", "ratio": 8}]) == []
