"""Разбор месячных цен Всемирного банка (commodity_service.parse_world_bank)."""
import io
import zipfile
from datetime import date

from app.services.market.commodity_service import MMBTU_PER_1000M3, parse_world_bank

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Description" sheetId="1" r:id="rId1"/><sheet name="Monthly Prices" sheetId="2" r:id="rId2"/></sheets>
</workbook>"""

_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/>
<Relationship Id="rId2" Target="/xl/worksheets/sheet2.xml" Type="x"/>
</Relationships>"""


def _book(rows: list[list[str]], strings: list[str]) -> bytes:
    """xlsx: строки листа «Monthly Prices»; текст — через общую таблицу строк."""
    def ref(col: int, row: int) -> str:
        return f"{chr(ord('A') + col)}{row}"

    body = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value in strings:
                cells.append(f'<c r="{ref(c, r)}" t="s"><v>{strings.index(value)}</v></c>')
            elif value:
                cells.append(f'<c r="{ref(c, r)}"><v>{value}</v></c>')
        body.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/'
             f'spreadsheetml/2006/main"><sheetData>{"".join(body)}</sheetData></worksheet>')
    shared = ('<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.org/'
              'spreadsheetml/2006/main">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", _WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", _RELS)
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet.replace("<sheetData>", "<sheetData><row r='1'/>"))
        z.writestr("xl/worksheets/sheet2.xml", sheet)
    return buf.getvalue()


def test_columns_found_by_header_with_tails_and_units_converted():
    header = ["", "Crude oil, average", "Natural gas, Europe", "Urea ", "Potassium chloride **", "Gold"]
    strings = [h for h in header if h] + ["($/mmbtu)", "…", "2012M12", "2024M01", "2024M02"]
    content = _book([
        ["World Bank Commodity Price Data"],
        header,
        ["", "($/bbl)", "($/mmbtu)", "($/mt)", "($/mt)", "($/troy oz)"],
        ["2012M12", "100", "10", "300", "400", "1700"],   # раньше 2013 — отбрасывается
        ["2024M01", "80", "10", "350", "…", "2030"],      # «…» — нет данных
        ["2024M02", "81", "8", "340", "300", "2020"],
    ], strings)

    out = parse_world_bank(content)

    assert out["gas_eu"] == [(date(2024, 1, 1), 10 * MMBTU_PER_1000M3), (date(2024, 2, 1), 8 * MMBTU_PER_1000M3)]
    assert out["urea"] == [(date(2024, 1, 1), 350.0), (date(2024, 2, 1), 340.0)]
    assert out["potash"] == [(date(2024, 2, 1), 300.0)]
    assert out["gold"][-1] == (date(2024, 2, 1), 2020.0)
    # Колонок, которых в файле нет, в ответе нет — без падения.
    assert "dap" not in out and "lng_asia" not in out


def test_daily_series_converted_by_last_known_rate():
    from app.services.market.commodity_service import _with_fx

    rows = [(date(2024, 1, 1), 30.0), (date(2024, 1, 2), 31.0), (date(2024, 1, 5), 32.0)]
    fx = [(date(2024, 1, 2), 1.1), (date(2024, 1, 4), 1.2)]
    # 1 января курса ещё нет — день пропущен; 5-го берётся курс 4-го.
    assert _with_fx(rows, fx) == [(date(2024, 1, 2), 31.0 * 1.1), (date(2024, 1, 5), 32.0 * 1.2)]
