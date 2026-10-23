"""Сырьё для графика цены: газ, СПГ, удобрения, золото, алмазы.

Нефти здесь нет — у неё свой дневной ряд (oil_service). У остального два
ряда — дневной биржевой, где он бесплатно есть, и месячный для лет раньше
него:

* дневные — закрытия ближних фьючерсов из Yahoo Finance: золото (COMEX
  GC), газ в Европе (TTF), СПГ в Азии (JKM), карбамид (CBOT, US Gulf).
  Ряды начинаются в разные годы: TTF — с 2017-го, карбамид — с 2020-го;
* месячные — «Pink Sheet» Всемирного банка (CMO-Historical-Data-Monthly.xlsx):
  средние цены за месяц. Для DAP и хлористого калия бесплатного дневного
  ряда нет — у них только месячный;
* алмазы — индекс импортных цен США на алмазы (BLS, ряд IP7102 в FRED),
  тоже месячный. Биржевой цены на алмазы нет вовсе: сделки частные, а
  прайс-листы Rapaport платные. Индекс показывает направление, а не цену
  карата.

Ряды лежат в той же таблице, что индексы Мосбиржи и нефть
(`market_index_values`): месячный — под кодом CMD_<КЛЮЧ> (точка месяца — на
его первое число), дневной — под CMD_<КЛЮЧ>_D.

Ссылка на файл Всемирного банка меняется каждый месяц, поэтому она каждый
раз берётся со страницы раздела. Файл разбирается стандартной библиотекой
(xlsx — это zip с XML): ради одной таблицы тянуть openpyxl незачем.
Колонки ищутся по заголовку, а не по букве — их порядок в файле менялся.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.market_index import MarketIndexValue
from app.services.market.index_service import store
from app.services.market.oil_service import priced_series
from app.utils.moex_client import _moex_get

logger = logging.getLogger(__name__)

_WB_PAGE = "https://www.worldbank.org/en/research/commodity-markets"
_FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
_YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
_UA = {"User-Agent": "Mozilla/5.0 (graham-analyzer)"}
FIRST_MONTH = date(2013, 1, 1)

# Газ в Европе Всемирный банк даёт в $ за миллион БТЕ, биржа TTF — в € за
# МВт·ч; в России его считают в $ за тысячу кубометров. Тысяча кубометров
# ≈ 35,8 млн БТЕ ≈ 10,5 МВт·ч.
MMBTU_PER_1000M3 = 35.8
MWH_PER_1000M3 = 10.5
# Фьючерс на карбамид CBOT котируется за короткую тонну (907 кг).
SHORT_TONS_PER_TONNE = 1.10231


@dataclass(frozen=True)
class Commodity:
    key: str
    label: str
    unit: str
    source: str
    #: Заголовок колонки в листе «Monthly Prices» Всемирного банка.
    wb_column: Optional[str] = None
    #: Ряд FRED, если не из Всемирного банка.
    fred_id: Optional[str] = None
    #: Множитель к значению источника (перевод единиц).
    scale: float = 1.0
    #: Индекс, а не цена: в рубли не переводится.
    index: bool = False
    #: Дневной биржевой ряд в Yahoo Finance — тикер ближнего фьючерса.
    yahoo: Optional[str] = None
    #: Множитель к дневному значению (перевод единиц).
    daily_scale: float = 1.0
    #: Валютный ряд Yahoo, на который умножить дневное значение (€ → $).
    daily_fx: Optional[str] = None
    daily_source: Optional[str] = None

    @property
    def code(self) -> str:
        return f"CMD_{self.key.upper()}"

    @property
    def daily_code(self) -> str:
        return f"CMD_{self.key.upper()}_D"


COMMODITIES: dict[str, Commodity] = {c.key: c for c in (
    Commodity("gas_eu", "Газ в Европе", "$/тыс. м³",
              "Всемирный банк, Natural gas, Europe (TTF), среднее за месяц",
              wb_column="Natural gas, Europe", scale=MMBTU_PER_1000M3,
              yahoo="TTF=F", daily_scale=MWH_PER_1000M3, daily_fx="EURUSD=X",
              daily_source="TTF (ближний фьючерс), € за МВт·ч в пересчёте по курсу евро"),
    Commodity("lng_asia", "СПГ в Азии", "$/млн БТЕ",
              "Всемирный банк, Liquefied natural gas, Japan, среднее за месяц",
              wb_column="Liquefied natural gas, Japan",
              yahoo="JKM=F", daily_source="JKM (ближний фьючерс, Япония и Корея)"),
    Commodity("urea", "Карбамид", "$/т",
              "Всемирный банк, Urea, среднее за месяц", wb_column="Urea",
              yahoo="UFV=F", daily_scale=SHORT_TONS_PER_TONNE,
              daily_source="карбамид FOB US Gulf (фьючерс CBOT)"),
    Commodity("dap", "Диаммонийфосфат (DAP)", "$/т",
              "Всемирный банк, DAP, среднее за месяц", wb_column="DAP"),
    Commodity("potash", "Хлористый калий", "$/т",
              "Всемирный банк, Potassium chloride, среднее за месяц",
              wb_column="Potassium chloride"),
    Commodity("gold", "Золото", "$/унц.",
              "Всемирный банк, Gold, среднее за месяц", wb_column="Gold",
              yahoo="GC=F", daily_source="COMEX (ближний фьючерс)"),
    Commodity("diamonds", "Алмазы, индекс цен", "индекс",
              "BLS, индекс импортных цен США на алмазы (FRED IP7102)",
              fred_id="IP7102", index=True),
)}


# ─── Всемирный банк ───────────────────────────────────────────────────────

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _wb_file() -> Optional[bytes]:
    try:
        page = _moex_get(_WB_PAGE, headers=_UA, timeout=40)
        page.raise_for_status()
        link = re.search(r'https://[^"\']*CMO-Historical-Data-Monthly\.xlsx', page.text)
        if not link:
            logger.warning("Всемирный банк: ссылки на месячные цены на странице нет")
            return None
        response = _moex_get(link.group(0), headers=_UA, timeout=90)
        response.raise_for_status()
        return response.content
    except Exception as exc:  # noqa: BLE001 — сеть
        logger.warning("Всемирный банк: файл цен не загрузился: %s", exc)
        return None


def _sheet_rows(content: bytes, sheet: str) -> list[dict[str, str]]:
    """Строки листа как {буква колонки: текст}."""
    book = zipfile.ZipFile(io.BytesIO(content))
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rel_id = next(s.get(f"{{{_NS['r']}}}id") for s in workbook.find("m:sheets", _NS) if s.get("name") == sheet)
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels if r.get("Id") == rel_id)
    path = "xl/" + target.lstrip("/").removeprefix("xl/")
    strings: list[str] = []
    if "xl/sharedStrings.xml" in book.namelist():
        shared = ET.fromstring(book.read("xl/sharedStrings.xml"))
        strings = ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")) for si in shared]
    rows = []
    for row in ET.fromstring(book.read(path)).iter(f"{{{_NS['m']}}}row"):
        cells = {}
        for cell in row:
            value = cell.find("m:v", _NS)
            if value is None or value.text is None:
                continue
            column = re.match(r"[A-Z]+", cell.get("r", "")).group()
            cells[column] = strings[int(value.text)] if cell.get("t") == "s" else value.text
        rows.append(cells)
    return rows


def parse_world_bank(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """{ключ сырья: [(первое число месяца, значение)]} из листа «Monthly Prices»."""
    rows = _sheet_rows(content, "Monthly Prices")
    header = next((r for r in rows if any(v.strip().startswith("Crude oil") for v in r.values())), None)
    if header is None:
        logger.warning("Всемирный банк: в листе нет строки заголовков")
        return {}
    # «Urea » и «Potassium chloride **» — заголовки с хвостами; сравниваем начало.
    clean = {col: re.sub(r"[\s*]+$", "", name.strip()) for col, name in header.items()}
    columns = {}
    for item in COMMODITIES.values():
        if item.wb_column is None:
            continue
        col = next((c for c, name in clean.items() if name == item.wb_column), None)
        if col is None:
            logger.warning("Всемирный банк: нет колонки «%s»", item.wb_column)
            continue
        columns[item.key] = col
    out: dict[str, list[tuple[date, float]]] = {key: [] for key in columns}
    for row in rows:
        month = re.fullmatch(r"(\d{4})M(\d{2})", row.get("A", ""))
        if not month:
            continue
        day = date(int(month.group(1)), int(month.group(2)), 1)
        if day < FIRST_MONTH:
            continue
        for key, col in columns.items():
            try:
                value = float(row.get(col, ""))
            except ValueError:  # «…» — нет данных за месяц
                continue
            out[key].append((day, value * COMMODITIES[key].scale))
    return out


# ─── FRED ─────────────────────────────────────────────────────────────────

def fetch_fred(series_id: str, since: date) -> list[tuple[date, float]]:
    try:
        response = _moex_get(_FRED, params={"id": series_id, "cosd": since.isoformat()}, timeout=30)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — сеть
        logger.warning("FRED %s не загрузился: %s", series_id, exc)
        return []
    rows = []
    for line in csv.reader(io.StringIO(response.text)):
        if len(line) != 2 or not line[0][:1].isdigit() or line[1] in ("", "."):
            continue
        rows.append((date.fromisoformat(line[0]), float(line[1])))
    return rows


# ─── Yahoo Finance: дневные закрытия ──────────────────────────────────────

def fetch_yahoo(symbol: str, since: date) -> list[tuple[date, float]]:
    """Дневные закрытия с `since`. Дата — по часовому поясу биржи: метка
    времени у Yahoo — начало торгов, и в UTC она бывает накануне."""
    start = int(datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    try:
        response = _moex_get(_YAHOO + symbol, headers=_UA, timeout=40, params={
            "period1": start, "period2": int(datetime.now(timezone.utc).timestamp()) + 86400,
            "interval": "1d",
        })
        response.raise_for_status()
        result = (response.json().get("chart") or {}).get("result") or []
    except Exception as exc:  # noqa: BLE001 — сеть
        logger.warning("Yahoo %s не загрузился: %s", symbol, exc)
        return []
    if not result:
        return []
    chart = result[0]
    offset = int((chart.get("meta") or {}).get("gmtoffset") or 0)
    stamps = chart.get("timestamp") or []
    closes = ((chart.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    by_day: dict[date, float] = {}
    for stamp, close in zip(stamps, closes):
        if close is None or close <= 0:
            continue
        by_day[datetime.fromtimestamp(stamp + offset, tz=timezone.utc).date()] = float(close)
    return sorted(by_day.items())


def _with_fx(rows: list[tuple[date, float]], fx: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Значение × последний известный на дату курс; без курса — пропуск."""
    out, j, rate = [], 0, None
    for day, value in rows:
        while j < len(fx) and fx[j][0] <= day:
            rate = fx[j][1]
            j += 1
        if rate is not None:
            out.append((day, value * rate))
    return out


# ─── Обновление и чтение ──────────────────────────────────────────────────

def refresh(db: Session) -> int:
    """Перекачать все ряды целиком: они месячные и короткие (≈160 точек), а
    Всемирный банк задним числом уточняет последние месяцы."""
    total = 0
    content = _wb_file()
    if content is not None:
        try:
            for key, rows in parse_world_bank(content).items():
                total += store(db, COMMODITIES[key].code, [(d, v, None, None) for d, v in rows])
        except Exception as exc:  # noqa: BLE001 — формат файла чужой
            logger.warning("Всемирный банк: файл не разобрался: %s", exc)
    for item in COMMODITIES.values():
        if item.fred_id:
            rows = fetch_fred(item.fred_id, FIRST_MONTH)
            total += store(db, item.code, [(d, v * item.scale, None, None) for d, v in rows])
    total += refresh_daily(db)
    return total


def refresh_daily(db: Session) -> int:
    """Докачать дневные ряды с последнего дня (с запасом в неделю: фьючерсы
    задним числом уточняют закрытие)."""
    total = 0
    for item in COMMODITIES.values():
        if not item.yahoo:
            continue
        last = db.query(func.max(MarketIndexValue.date)).filter(MarketIndexValue.code == item.daily_code).scalar()
        since = FIRST_MONTH if last is None else last - timedelta(days=7)
        rows = fetch_yahoo(item.yahoo, since)
        if item.daily_fx:
            # Курс — с запасом назад, чтобы у первого дня он был.
            rows = _with_fx(rows, fetch_yahoo(item.daily_fx, since - timedelta(days=14)))
        total += store(db, item.daily_code, [(d, v * item.daily_scale, None, None) for d, v in rows])
    return total


def series(db: Session, key: str, since: Optional[date] = None) -> list[tuple[date, float, Optional[float]]]:
    """Месячный ряд: (первое число месяца, значение, курс ₽/$ на эту дату)."""
    return priced_series(db, COMMODITIES[key].code, since)


def daily_series(db: Session, key: str, since: Optional[date] = None) -> list[tuple[date, float, Optional[float]]]:
    """Дневной биржевой ряд: (день, значение, курс ₽/$); пустой, если его нет."""
    item = COMMODITIES[key]
    return priced_series(db, item.daily_code, since) if item.yahoo else []
