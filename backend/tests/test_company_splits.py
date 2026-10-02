"""Сплиты из двух источников и приведение к нынешним акциям."""

from datetime import date
from types import SimpleNamespace

from app.services.share_splits import company_splits, shares_factor, split_note


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows


class FakeDb:
    def __init__(self, events):
        self.events = events

    def query(self, _model):
        return FakeQuery(self.events)


def event(day, ratio):
    return SimpleNamespace(date=day, value=ratio)


def test_дробление_из_карточки_и_из_событий_биржи_складываются():
    """Белуга есть только в карточке, Норникель — только у Мосбиржи."""
    company = SimpleNamespace(id=1, share_splits=[{"date": "2024-08-22", "ratio": 8}])
    db = FakeDb([event(date(2021, 1, 15), 2.0)])
    splits = company_splits(db, company)
    assert [s["date"] for s in splits] == ["2021-01-15", "2024-08-22"]
    # До обоих сплитов цена делится на 16, между ними — на 8.
    assert shares_factor(splits, date(2020, 12, 31)) == 16.0
    assert shares_factor(splits, date(2023, 6, 1)) == 8.0
    assert shares_factor(splits, date(2024, 8, 22)) == 1.0


def test_одна_дата_из_двух_источников_считается_один_раз():
    company = SimpleNamespace(id=1, share_splits=[{"date": "2024-08-22", "ratio": 8}])
    db = FakeDb([event(date(2024, 8, 22), 8.0)])
    assert len(company_splits(db, company)) == 1


def test_цена_белуги_до_сплита_сравнима_с_нынешней():
    """5 000 ₽ до дробления 8:1 — это 625 ₽ на нынешнюю акцию."""
    splits = [{"date": "2024-08-22", "ratio": 8}]
    assert 5000 / shares_factor(splits, date(2024, 8, 21)) == 625


def test_подпись_называет_сплит():
    note = split_note([{"date": "2024-08-22", "ratio": 8}])
    assert "дробление 8:1 от 22.08.2024" in note
    assert split_note([]) is None
    assert "консолидация 1:5000" in split_note([{"date": "2024-07-15", "ratio": 0.0002}])


def test_шкала_отчёта_по_его_числу_акций():
    from app.services.share_splits import report_split_factor
    t = [{"date": "2026-04-17", "ratio": 10}]
    # Т: годовой за 2025-й вышел до дробления — делить на 10.
    assert report_split_factor(t, date(2025, 12, 31), 257_393_950, 2_549_948_000) == 10
    # Транснефть: отчёт за 2023-й эмитент уже пересчитал (IAS 33) — не делить.
    trnfp = [{"date": "2024-02-21", "ratio": 100}]
    assert report_split_factor(trnfp, date(2023, 12, 31), 724_934_300, 724_934_300) == 1
    assert report_split_factor(trnfp, date(2022, 12, 31), 7_249_343, 724_934_300) == 100
