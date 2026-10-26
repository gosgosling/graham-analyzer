import json

from app.config import settings
from app.services.reports import report_files
from app.services.reports.report_files import report_file


def _manifest(tmp_path, monkeypatch, data):
    (tmp_path / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(settings, "REPORT_FILES_DIR", str(tmp_path))
    report_files._cache.update({"mtime": None, "data": {}})


def test_файл_находится_по_пути_из_разбора(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch, {"files": {
        "/home/x/Reports/UPRO/UPRO_2025.pdf": {"path": "UPRO/UPRO_2025.pdf", "size": 10, "sha256": "ab"},
    }})
    assert report_file("/home/x/Reports/UPRO/UPRO_2025.pdf") == {
        "url": "/files/reports/UPRO/UPRO_2025.pdf", "size": 10, "sha256": "ab",
    }
    assert report_file("/home/x/Reports/UPRO/UPRO_2024.pdf") is None


def test_без_пути_файл_находится_по_компании_году_и_периоду(tmp_path, monkeypatch):
    _manifest(tmp_path, monkeypatch, {
        "by_name": {"LKOH/LKOH_2026_H1.pdf": {"path": "LKOH/LKOH_2026_H1.pdf", "size": 5, "sha256": "cd"}},
        "reports": {"7:2026:SEMI_ANNUAL": "LKOH/LKOH_2026_H1.pdf"},
    })
    assert report_file(None, 7, 2026, "semi_annual")["url"] == "/files/reports/LKOH/LKOH_2026_H1.pdf"
    assert report_file(None, 7, 2026, "annual") is None


def test_нет_манифеста_нет_ссылок(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "REPORT_FILES_DIR", str(tmp_path))
    report_files._cache.update({"mtime": None, "data": {}})
    assert report_file("/any.pdf", 1, 2025, "annual") is None
