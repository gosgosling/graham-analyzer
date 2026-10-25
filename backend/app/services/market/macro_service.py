"""Экономика страны: бюджет, ФНБ, госдолг, инфляция, резервы, платёжный баланс.

Для раздела «Экономика». Ряды лежат в той же таблице, что индексы Мосбиржи,
нефть и сырьё (`market_index_values`), под кодами `M_*` (не длиннее 16
символов — так задан столбец). Точка помесячного ряда стоит на первое число
своего месяца, квартального — на первое число первого месяца квартала,
годового — на 1 января.

Источники — только открытые файлы без ключей:

* **Минфин** — исполнение федерального бюджета помесячно с 2011 года
  (накопленным итогом с начала года, млрд ₽), ФНБ помесячно с 2008-го,
  госдолг в ОФЗ: по годам с 1993-го и помесячно за текущий год. Имена файлов
  меняются каждый месяц, поэтому ссылка каждый раз берётся со страницы
  раздела — как у Всемирного банка в `commodity_service`;
* **ЦБ** — инфляция год к году (таблица на сайте), опрос населения
  «инФОМ» (медианные ожидаемая и наблюдаемая инфляция, индекс потребительских
  настроений), международные резервы, платёжный баланс по кварталам,
  курсы евро и юаня (доллар уже грузит `oil_service`);
* **Всемирный банк** — рост ВВП, ВВП в рублях и безработица по годам.
  Росстат и МВФ с сервера недоступны (таймаут и 403), а годовых рядов ВБ для
  картины хватает: квартальный ВВП здесь не нужен.

Чего нет: реальных зарплат (только Росстат) и Urals помесячно (Минфин даёт
его текстом).

Бюджет хранится как опубликован — накопленным итогом. Месяц и сумма за
двенадцать месяцев считаются при выдаче (`budget_flows`): так файл Минфина
и база совпадают строка в строку, и проверить число можно по первоисточнику.

Файлы xlsx разбираются стандартной библиотекой (`commodity_service._sheet_rows`).
Строки ищутся по коду строки («1.1.», «2.2.»), а не по номеру: Минфин
вставляет примечания, и номера строк в файле плывут.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.market_index import MarketIndexValue
from app.services.market.commodity_service import _sheet_rows
from app.services.market.index_service import store
from app.utils.moex_client import _moex_get

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (graham-analyzer)"}
_MINFIN = "https://minfin.gov.ru"
_CBR = "https://www.cbr.ru"


@dataclass(frozen=True)
class Series:
    code: str
    label: str
    unit: str
    freq: str  # day | month | quarter | year
    source: str


_BUDGET_SRC = "Минфин, исполнение федерального бюджета (накопленным итогом с начала года)"
_FNB_SRC = "Минфин, ФНБ на конец месяца"
_DEBT_SRC = "Минфин, государственный внутренний долг в ценных бумагах"
_INFOM_SRC = "ЦБ, опрос населения «инФОМ» (медиана)"
_BOP_SRC = "ЦБ, платёжный баланс (стандартные компоненты)"
_WB_SRC = "Всемирный банк (World Development Indicators)"
_RULE_SRC = "Минфин, сведения о нефтегазовых доходах и операциях бюджетного правила"
_CREDIT_SRC = "ЦБ, денежные агрегаты и кредит экономике"

# Закон о бюджете в первоначальной редакции, трлн ₽: доходы, расходы, дефицит
# (минус) или профицит. Машиночитаемого ряда параметров закона нет —
# Минфин публикует их текстом в пояснительных записках, поэтому таблица
# ведётся здесь и пополняется раз в год, когда закон подписан. Поправки
# в течение года сюда не вносятся: сравнение «как планировали в начале» и
# есть то, что показывает, насколько бюджет уходит от плана.
BUDGET_LAW = {
    2022: (25.02, 23.69, 1.33),    # 390-ФЗ от 06.12.2021
    2023: (26.13, 29.06, -2.93),   # 466-ФЗ от 05.12.2022
    2024: (35.06, 36.66, -1.60),   # 540-ФЗ от 27.11.2023
    2025: (40.30, 41.47, -1.17),   # 419-ФЗ от 30.11.2024
    2026: (40.28, 44.07, -3.79),   # закон о бюджете на 2026–2028 годы
}

# Код строки в файле Минфина → наш код. Порядок — как на странице.
BUDGET_ROWS = {
    "1": ("M_BUD_REV", "Доходы"),
    "1.1": ("M_BUD_REV_OG", "Нефтегазовые доходы"),
    "1.2": ("M_BUD_REV_NOG", "Ненефтегазовые доходы"),
    "1.2.1.1": ("M_BUD_VAT", "НДС внутренний"),
    "1.2.1.3": ("M_BUD_PROFIT", "Налог на прибыль"),
    "2": ("M_BUD_EXP", "Расходы"),
    "2.2": ("M_BUD_EXP_DEF", "Национальная оборона"),
    "2.3": ("M_BUD_EXP_SEC", "Безопасность и правоохранительная деятельность"),
    "2.4": ("M_BUD_EXP_ECON", "Национальная экономика"),
    "2.9": ("M_BUD_EXP_HLTH", "Здравоохранение"),
    "2.7": ("M_BUD_EXP_EDU", "Образование"),
    "2.10": ("M_BUD_EXP_SOC", "Социальная политика"),
    "2.13": ("M_BUD_EXP_DEBT", "Обслуживание госдолга"),
    "3": ("M_BUD_BAL", "Дефицит (−) / профицит (+)"),
    "3.1": ("M_BUD_BAL_NOG", "Ненефтегазовый дефицит"),
    "4.1.2": ("M_BUD_FIN_DOM", "Сальдо внутреннего долга (ОФЗ)"),
    "4.1.5": ("M_BUD_FIN_FX", "Курсовая разница"),
    "4.1.6": ("M_BUD_FIN_ACC", "Изменение остатков на счетах"),
    "4.1.7": ("M_BUD_FIN_OTH", "Прочие внутренние источники"),
    "4.2": ("M_BUD_FIN_EXT", "Внешние источники"),
}

SERIES: dict[str, Series] = {
    **{code: Series(code, label, "млрд ₽", "month", _BUDGET_SRC) for code, label in BUDGET_ROWS.values()},
    "M_FNB": Series("M_FNB", "ФНБ", "млрд ₽", "month", _FNB_SRC),
    "M_FNB_OTHER": Series("M_FNB_OTHER", "ФНБ в иных активах (акции, облигации, депозиты)", "млрд ₽", "month", _FNB_SRC),
    "M_FNB_GDP": Series("M_FNB_GDP", "ФНБ к ВВП", "%", "month", _FNB_SRC),
    "M_FNB_USD": Series("M_FNB_USD", "ФНБ в долларах", "млрд $", "month", _FNB_SRC),
    "M_DEBT_DOM": Series("M_DEBT_DOM", "Госдолг в ОФЗ", "млрд ₽", "month", _DEBT_SRC),
    "M_INFL": Series("M_INFL", "Инфляция год к году", "%", "month", "ЦБ, инфляция и ключевая ставка"),
    "M_INFL_TARGET": Series("M_INFL_TARGET", "Цель по инфляции", "%", "month", "ЦБ"),
    "M_INFL_EXP": Series("M_INFL_EXP", "Ожидаемая населением инфляция через год", "%", "month", _INFOM_SRC),
    "M_INFL_OBS": Series("M_INFL_OBS", "Наблюдаемая населением инфляция", "%", "month", _INFOM_SRC),
    "M_CSI": Series("M_CSI", "Индекс потребительских настроений", "пункты", "month", _INFOM_SRC),
    "M_RES": Series("M_RES", "Международные резервы", "млрд $", "month", "ЦБ, международные резервы на начало месяца"),
    "M_RES_GOLD": Series("M_RES_GOLD", "в т. ч. монетарное золото", "млрд $", "month", "ЦБ, международные резервы на начало месяца"),
    "M_BOP_CA": Series("M_BOP_CA", "Счёт текущих операций", "млрд $", "quarter", _BOP_SRC),
    "M_BOP_EXP": Series("M_BOP_EXP", "Экспорт товаров", "млрд $", "quarter", _BOP_SRC),
    "M_BOP_IMP": Series("M_BOP_IMP", "Импорт товаров", "млрд $", "quarter", _BOP_SRC),
    "M_GDP_GROWTH": Series("M_GDP_GROWTH", "Рост ВВП", "%", "year", _WB_SRC),
    "M_GDP": Series("M_GDP", "ВВП в текущих ценах", "млрд ₽", "year", _WB_SRC),
    "M_UNEMP": Series("M_UNEMP", "Безработица", "%", "year", _WB_SRC),
    "M_OG_BASE": Series("M_OG_BASE", "Базовые нефтегазовые доходы", "млрд ₽", "month", _RULE_SRC),
    "M_OG_EXTRA": Series("M_OG_EXTRA", "Дополнительные нефтегазовые доходы", "млрд ₽", "month", _RULE_SRC),
    "M_FX_OPS": Series("M_FX_OPS", "Покупка (+) / продажа (−) валюты Минфином", "млрд ₽", "month", _RULE_SRC),
    "M_CREDIT": Series("M_CREDIT", "Кредит экономике, год к году", "%", "month", _CREDIT_SRC),
    "M_CREDIT_CORP": Series("M_CREDIT_CORP", "Кредиты компаниям, год к году", "%", "month", _CREDIT_SRC),
    "M_CREDIT_HH": Series("M_CREDIT_HH", "Кредиты людям, год к году", "%", "month", _CREDIT_SRC),
    "M_M2": Series("M_M2", "Денежная масса М2, год к году", "%", "month", _CREDIT_SRC),
    "M_INCOME": Series("M_INCOME", "Медианный располагаемый доход на человека", "тыс. ₽ в месяц", "month", _INFOM_SRC),
    "M_OFZ_INT": Series("M_OFZ_INT", "Проценты по ОФЗ за год вперёд, оценка", "млрд ₽", "day",
                        "Мосбиржа, текущие купоны и объёмы ОФЗ в обращении"),
    "EURRUB": Series("EURRUB", "Евро", "₽", "day", "ЦБ, официальный курс"),
    "CNYRUB": Series("CNYRUB", "Юань", "₽", "day", "ЦБ, официальный курс"),
}

_MONTHS = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
_EXCEL_EPOCH = date(1899, 12, 30)


# ─── Общее ──────────────────────────────────────────────────────────────────


def _get(url: str, timeout: int = 60, **kwargs):
    response = _moex_get(url, headers=_UA, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response


def _link(page: str, pattern: str, base: str) -> Optional[str]:
    """Первая ссылка на странице по образцу — у Минфина и ЦБ это самый свежий файл."""
    found = re.search(pattern, _get(page).text)
    return base + html_lib.unescape(found.group(0)) if found else None


def _number(text: Optional[str]) -> Optional[float]:
    if text is None:
        return None
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _month_of(header: str) -> Optional[date]:
    """Заголовок столбца → первое число месяца. Бывает числом Excel
    (40544 — январь 2011) и текстом с пометкой («сен.26 **», «Январь 2008¹»)."""
    value = _number(header)
    if value is not None and value > 30000:
        day = _EXCEL_EPOCH + timedelta(days=int(value))
        return date(day.year, day.month, 1)
    text = header.lower()
    for i, name in enumerate(_MONTHS):
        if text.startswith(name) or text.startswith({"май": "мая"}.get(name, name)):
            year = re.search(r"(\d{4}|\d{2})", text[3:])
            if not year:
                return None
            y = int(year.group(1))
            return date(y + 2000 if y < 100 else y, i + 1, 1)
    return None


def _row_code(cell: str) -> str:
    return cell.strip().rstrip(".").strip()


def _table(content: bytes, sheet: str, header_row: int) -> dict[str, list[tuple[date, float]]]:
    """Лист «код строки | название | значения по месяцам» → {код: [(месяц, значение)]}."""
    rows = _sheet_rows(content, sheet)
    months = {col: _month_of(text) for col, text in rows[header_row].items()}
    out: dict[str, list[tuple[date, float]]] = {}
    for row in rows[header_row + 1:]:
        code = _row_code(row.get("A", ""))
        if not code or not code[0].isdigit():
            continue
        points = []
        for col, month in months.items():
            value = _number(row.get(col))
            if month is not None and value is not None:
                points.append((month, value))
        out.setdefault(code, sorted(points))
    return out


def _rows(points: list[tuple[date, float]]) -> list[tuple]:
    return [(day, value, None, None) for day, value in points]


# ─── Минфин ─────────────────────────────────────────────────────────────────


def parse_budget(content: bytes) -> dict[str, list[tuple[date, float]]]:
    table = _table(content, "месяц", 2)
    return {code: table.get(row, []) for row, (code, _label) in BUDGET_ROWS.items()}


def parse_fnb(content: bytes) -> dict[str, list[tuple[date, float]]]:
    table = _table(content, "Таблица по ФНБ", 2)
    return {
        "M_FNB": table.get("2", []),
        "M_FNB_OTHER": table.get("5", []),
        # В файле доля, а не проценты: 0,055 — это 5,5% ВВП.
        "M_FNB_GDP": [(d, v * 100) for d, v in table.get("2.1", [])],
        "M_FNB_USD": table.get("3.1", []),
    }


def parse_debt_annual(content: bytes) -> list[tuple[date, float]]:
    """«на 01.01.2026 | … | итого» по годам. Остаток на 1 января — это конец
    декабря прошлого года; точка ставится на декабрь, как и помесячные."""
    out = []
    for row in _sheet_rows(content, "Лист1"):
        found = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", row.get("B", ""))
        total = _number(row.get("R"))
        if found and total is not None:
            on = date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
            prev = on - timedelta(days=1)
            out.append((date(prev.year, prev.month, 1), total))
    return out


def parse_debt_months(content: bytes) -> list[tuple[date, float]]:
    """Текущий год по месяцам: дата числом Excel в B, «Итого» — последний столбец."""
    rows = _sheet_rows(content, next(iter(_sheet_names(content))))
    header = next((r for r in rows if any("Итого" in v for v in r.values())), None)
    if header is None:
        return []
    total_col = next(col for col, v in header.items() if "Итого" in v)
    out = []
    for row in rows:
        on = _number(row.get("B"))
        total = _number(row.get(total_col))
        if on and on > 30000 and total is not None:
            day = _EXCEL_EPOCH + timedelta(days=int(on)) - timedelta(days=1)
            out.append((date(day.year, day.month, 1), total))
    return out


def _sheet_names(content: bytes) -> list[str]:
    import io
    import zipfile

    workbook = zipfile.ZipFile(io.BytesIO(content)).read("xl/workbook.xml").decode()
    return [html_lib.unescape(n) for n in re.findall(r'<sheet [^>]*name="([^"]+)"', workbook)]


def fetch_minfin() -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = {}
    jobs: list[tuple[str, str, Callable]] = [
        ("/ru/statistics/fedbud/execute", r"/common/upload/library/[^\"]+_mes\.xlsx", parse_budget),
        ("/ru/perfomance/nationalwealthfund/statistics", r"/common/upload/library/[^\"]+/Dannye_\d{8}\.xlsx", parse_fnb),
        ("/ru/statistics/fedbud/oil", r"/common/upload/library/[^\"]+/Svedeniya_\d{8}\.xlsx", parse_oil_rule),
    ]
    for page, pattern, parse in jobs:
        try:
            link = _link(_MINFIN + page, pattern, _MINFIN)
            if link:
                out.update(parse(_get(link, timeout=90).content))
        except Exception as exc:  # noqa: BLE001 — сеть или формат: остальное грузим
            logger.warning("Минфин %s не загрузился: %s", page, exc)

    # Госдолг: годовой ряд с 1993-го и помесячный за текущий год — в одном ряду.
    debt: dict[date, float] = {}
    page = _MINFIN + "/ru/perfomance/public_debt/internal/structure"
    for pattern, parse in (
        (r"/common/upload/library/[^\"]+/Obem_gos_vnutr__dolga_s_93_goda[^\"]*\.xlsx", parse_debt_annual),
        (r"/common/upload/library/[^\"]+/debtDynamics_ru_[\d.]+\.xlsx", parse_debt_months),
    ):
        try:
            link = _link(page, pattern, _MINFIN)
            if link:
                debt.update(dict(parse(_get(link).content)))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Госдолг Минфина не загрузился (%s): %s", pattern, exc)
    if debt:
        out["M_DEBT_DOM"] = sorted(debt.items())
    return out


# ─── ЦБ ─────────────────────────────────────────────────────────────────────


_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)


def _html_rows(text: str) -> list[list[str]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip() for c in _TD.findall(tr)]
        if cells:
            rows.append(cells)
    return rows


def parse_inflation(text: str) -> dict[str, list[tuple[date, float]]]:
    """Строки «09.2026 | 14,00 | 6,35 | 4,00»: месяц, ключевая, инфляция, цель."""
    infl, target = [], []
    for cells in _html_rows(text):
        found = re.fullmatch(r"(\d{2})\.(\d{4})", cells[0])
        if not found or len(cells) < 3:
            continue
        month = date(int(found.group(2)), int(found.group(1)), 1)
        if (value := _number(cells[2])) is not None:
            infl.append((month, value))
        if len(cells) > 3 and (value := _number(cells[3])) is not None:
            target.append((month, value))
    return {"M_INFL": sorted(infl), "M_INFL_TARGET": sorted(target)}


def parse_reserves(text: str) -> dict[str, list[tuple[date, float]]]:
    """«01.10.2026 | 712 345 | … | золото»: всего и золото, млн $ → млрд $.
    Остаток на 1-е число — это конец прошлого месяца, точка на него."""
    total, gold = [], []
    for cells in _html_rows(text):
        found = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", cells[0])
        if not found or len(cells) < 7:
            continue
        on = date(int(found.group(3)), int(found.group(2)), int(found.group(1))) - timedelta(days=1)
        month = date(on.year, on.month, 1)
        if (value := _number(cells[1])) is not None:
            total.append((month, value / 1000))
        if (value := _number(cells[-1])) is not None:
            gold.append((month, value / 1000))
    return {"M_RES": sorted(total), "M_RES_GOLD": sorted(gold)}


def parse_infom(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """Лист «Данные за все годы»: даты числами Excel во второй строке, ряды —
    по подписи в столбце A. Подписи повторяются в разных блоках (по группам
    населения), поэтому берётся первая после заголовка блока."""
    rows = _sheet_rows(content, "Данные за все годы")
    header = next(r for r in rows if sum(1 for v in r.values() if (_number(v) or 0) > 39000) > 50)
    months = {col: _month_of(text) for col, text in header.items()}

    def after(block: str, label: str) -> list[tuple[date, float]]:
        inside = False
        for row in rows:
            name = row.get("A", "").strip().lower()
            # Сначала строка данных, потом заголовок блока: у дохода подпись
            # строки начинается так же, как заголовок.
            if inside and name.startswith(label):
                return sorted(
                    (m, v) for col, m in months.items()
                    if m is not None and (v := _number(row.get(col))) is not None
                )
            if name.startswith(block):
                inside = True
        return []

    return {
        "M_INFL_OBS": after("прямые оценки годовой инфляции: медиан", "наблюдаемая инфляция"),
        "M_INFL_EXP": after("прямые оценки годовой инфляции: медиан", "ожидаемая инфляция"),
        "M_CSI": after("индекс потребительских настроений (ипн)", "индекс потребительских настроений"),
        "M_INCOME": after("медианное значение среднедушевого располагаемого дохода", "медианное значение"),
    }


def parse_bop(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """Лист «Кварталы»: «2 квартал 2026 г.» в заголовке, млн $ → млрд $.
    Экспорт и импорт — первые строки «Экспорт»/«Импорт» после «Товары »."""
    rows = _sheet_rows(content, "Кварталы")
    header = next(r for r in rows if any("квартал" in v for v in r.values()))
    quarters = {}
    for col, text in header.items():
        found = re.search(r"(\d)\s*квартал\s*(\d{4})", text)
        if found:
            quarters[col] = date(int(found.group(2)), (int(found.group(1)) - 1) * 3 + 1, 1)

    def values(row) -> list[tuple[date, float]]:
        return sorted((q, v / 1000) for col, q in quarters.items() if (v := _number(row.get(col))) is not None)

    out: dict[str, list[tuple[date, float]]] = {}
    goods = False
    for row in rows:
        name = row.get("A", "").strip()
        if name.startswith("Счет текущих операций") and "M_BOP_CA" not in out:
            out["M_BOP_CA"] = values(row)
        elif name == "Товары":
            goods = True
        elif goods and name == "Экспорт" and "M_BOP_EXP" not in out:
            out["M_BOP_EXP"] = values(row)
        elif goods and name == "Импорт" and "M_BOP_IMP" not in out:
            out["M_BOP_IMP"] = values(row)
            goods = False
    return out


def parse_oil_rule(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """«Сведения о формировании и использовании дополнительных нефтегазовых
    доходов»: даты числами Excel в строке «Показатели», ряды — по подписи."""
    rows = _sheet_rows(content, _sheet_names(content)[0])
    header = next(r for r in rows if r.get("A", "").strip().startswith("Показатели"))
    months = {col: _month_of(text) for col, text in header.items() if col != "A"}
    wanted = {
        "базовый месячный объем": "M_OG_BASE",
        "дополнительные нефтегазовые доходы": "M_OG_EXTRA",
        "объем покупки (продажи) иностранной валюты": "M_FX_OPS",
    }
    out: dict[str, list[tuple[date, float]]] = {}
    for row in rows:
        name = row.get("A", "").strip().lower()
        code = next((c for prefix, c in wanted.items() if name.startswith(prefix)), None)
        if code and code not in out:
            out[code] = sorted((m, v) for col, m in months.items()
                               if m is not None and (v := _number(row.get(col))) is not None)
    return out


def parse_credit(content: bytes) -> dict[str, list[tuple[date, float]]]:
    """Лист «YOY» таблицы «Денежные агрегаты и кредит экономике»: годовые
    темпы, % — на 1-е число месяца; точка ставится на прошлый месяц."""
    rows = _sheet_rows(content, "YOY")
    header = rows[0]
    months: dict[str, date] = {}
    for col, text in header.items():
        month = _month_of(text)
        if month is not None:
            prev = month - timedelta(days=1)
            months[col] = date(prev.year, prev.month, 1)
    wanted = {
        "кредит экономике": "M_CREDIT",
        "корпоративные кредиты": "M_CREDIT_CORP",
        "кредиты физическим лицам": "M_CREDIT_HH",
        "денежная масса м2": "M_M2",
    }
    out: dict[str, list[tuple[date, float]]] = {}
    for row in rows[1:]:
        name = row.get("A", "").strip().lower()
        code = wanted.get(name)
        if code and code not in out:
            out[code] = sorted((m, v) for col, m in months.items() if (v := _number(row.get(col))) is not None)
    return out


def ofz_interest(db: Session) -> Optional[float]:
    """Сколько государство заплатит процентов по ОФЗ за год вперёд при
    нынешних купонах, млрд ₽.

    Расходы на обслуживание долга Минфин с 2022 года по месяцам не раскрывает,
    поэтому это оценка снизу вверх: по каждому выпуску в обращении — объём ×
    номинал × купон. У флоатеров (ОФЗ-ПК) купон следующего периода ещё не
    известен — берётся ключевая ставка: они привязаны к RUONIA, а она идёт за
    ключевой. У линкеров (ОФЗ-ИН) номинал уже проиндексирован, купон 2,5% —
    индексация номинала в проценты не входит. Юаневые выпуски — по курсу ЦБ.
    """
    from app.models.key_rate_daily import KeyRateDaily

    try:
        data = _get("https://iss.moex.com/iss/engines/stock/markets/bonds/boards/TQOB/securities.json", params={
            "iss.meta": "off",
            "securities.columns": "SECID,COUPONPERCENT,FACEVALUE,ISSUESIZEPLACED,FACEUNIT",
        }).json()["securities"]["data"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("ОФЗ с Мосбиржи не загрузились: %s", exc)
        return None
    key = db.query(KeyRateDaily).order_by(KeyRateDaily.date.desc()).first()
    cny = db.query(MarketIndexValue).filter(MarketIndexValue.code == "CNYRUB").order_by(MarketIndexValue.date.desc()).first()
    total = 0.0
    for secid, coupon, face, placed, unit in data:
        if not placed or not face:
            continue
        if coupon is None:
            if not str(secid).startswith("SU29") or key is None:
                continue
            coupon = float(key.rate)
        fx = 1.0
        if unit == "CNY":
            if cny is None:
                continue
            fx = float(cny.close)
        total += float(placed) * float(face) * fx * float(coupon) / 100
    return round(total / 1e9, 1) if total else None


def fetch_cbr() -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = {}
    today = date.today()
    jobs: list[tuple[str, Callable[[], dict]]] = [
        ("инфляция", lambda: parse_inflation(_get(
            f"{_CBR}/hd_base/infl/?UniDbQuery.Posted=True&UniDbQuery.From=01.01.2008"
            f"&UniDbQuery.To={today:%d.%m.%Y}").text)),
        ("резервы", lambda: parse_reserves(_get(
            f"{_CBR}/hd_base/mrrf/mrrf_m/?UniDbQuery.Posted=True&UniDbQuery.From=01.2008"
            f"&UniDbQuery.To={today:%m.%Y}").text)),
        ("инФОМ", lambda: parse_infom(_get(_link(
            f"{_CBR}/analytics/dkp/inflationary_expectations/",
            r"/Collection/Collection/File/\d+/Infl_exp_[\d-]+\.xlsx", _CBR)).content)),
        ("кредит и М2", lambda: parse_credit(_get(_link(
            f"{_CBR}/statistics/macro_itm/dkfs/", r"/Content/Document/File/\d+/credit_m2x\.xlsx", _CBR),
            timeout=90).content)),
        ("платёжный баланс", lambda: parse_bop(_get(
            f"{_CBR}/vfs/statistics/credit_statistics/bop/bal_of_payments_standart.xlsx", timeout=120).content)),
    ]
    for name, job in jobs:
        try:
            out.update(job())
        except Exception as exc:  # noqa: BLE001
            logger.warning("ЦБ, %s: не загрузилось: %s", name, exc)
    return out


_CURRENCIES = {"EURRUB": "R01239", "CNYRUB": "R01375"}
FIRST_DAY = date(2013, 1, 1)


def fetch_currency(cbr_id: str, since: date) -> list[tuple[date, float]]:
    try:
        response = _get(f"{_CBR}/scripts/XML_dynamic.asp", timeout=30, params={
            "date_req1": since.strftime("%d/%m/%Y"), "date_req2": date.today().strftime("%d/%m/%Y"),
            "VAL_NM_RQ": cbr_id,
        })
        root = ET.fromstring(response.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Курс %s ЦБ не загрузился: %s", cbr_id, exc)
        return []
    rows = []
    for record in root.findall("Record"):
        day = date(*reversed([int(x) for x in record.attrib["Date"].split(".")]))
        nominal = _number(record.findtext("Nominal", "1")) or 1
        value = _number(record.findtext("Value"))
        if value is not None:
            rows.append((day, value / nominal))
    return rows


# ─── Всемирный банк ─────────────────────────────────────────────────────────

_WB = {
    "M_GDP_GROWTH": ("NY.GDP.MKTP.KD.ZG", 1),
    "M_GDP": ("NY.GDP.MKTP.CN", 1e-9),  # рубли → млрд ₽
    "M_UNEMP": ("SL.UEM.TOTL.ZS", 1),
}


def fetch_world_bank() -> dict[str, list[tuple[date, float]]]:
    out = {}
    for code, (indicator, scale) in _WB.items():
        try:
            data = _get(f"https://api.worldbank.org/v2/country/RUS/indicator/{indicator}",
                        params={"format": "json", "per_page": 100, "date": "2000:2100"}).json()
            out[code] = sorted(
                (date(int(item["date"]), 1, 1), float(item["value"]) * scale)
                for item in data[1] if item.get("value") is not None
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Всемирный банк %s не загрузился: %s", indicator, exc)
    return out


# ─── Загрузка и выдача ──────────────────────────────────────────────────────


def refresh(db: Session) -> int:
    """Всё разом. Файлы небольшие и перечитываются целиком: Минфин и ЦБ
    уточняют прошлые месяцы задним числом (предварительные данные бюджета
    помечены звёздочками), и докачка «с последней даты» эти правки бы теряла.
    Курсы — дневные, их докачиваем с последнего дня."""
    total = 0
    for fetch in (fetch_minfin, fetch_cbr, fetch_world_bank):
        for code, points in fetch().items():
            if points:
                total += store(db, code, _rows(points))
    for code, cbr_id in _CURRENCIES.items():
        last = db.query(func.max(MarketIndexValue.date)).filter(MarketIndexValue.code == code).scalar()
        since = FIRST_DAY if last is None else last - timedelta(days=7)
        total += store(db, code, _rows(fetch_currency(cbr_id, since)))
    # Проценты по ОФЗ — одна точка в день: истории у Мосбиржи нет, она
    # копится с первого запуска.
    interest = ofz_interest(db)
    if interest is not None:
        total += store(db, "M_OFZ_INT", _rows([(date.today(), interest)]))
    return total


def load(db: Session, codes) -> dict[str, list[tuple[date, float]]]:
    out: dict[str, list[tuple[date, float]]] = {code: [] for code in codes}
    query = (db.query(MarketIndexValue.code, MarketIndexValue.date, MarketIndexValue.close)
             .filter(MarketIndexValue.code.in_(list(codes)))
             .order_by(MarketIndexValue.code, MarketIndexValue.date))
    for code, day, value in query:
        out[code].append((day, float(value)))
    return out


def budget_flows(cumulative: list[tuple[date, float]]) -> tuple[list[tuple[date, float]], list[tuple[date, float]]]:
    """Накопленный итог → (за месяц, за последние 12 месяцев).

    Месяц — разность с прошлым месяцем того же года (январь — как есть).
    Двенадцать месяцев — накопленное с начала года плюс прошлый год целиком
    минус прошлый год по тот же месяц; считается, только если все три числа
    есть, иначе точка пропускается."""
    by_month = dict(cumulative)
    month, rolling = [], []
    for day, value in cumulative:
        prev = by_month.get(date(day.year, day.month - 1, 1)) if day.month > 1 else 0.0
        if prev is not None:
            month.append((day, value - prev))
        last_year_total = by_month.get(date(day.year - 1, 12, 1))
        last_year_same = by_month.get(date(day.year - 1, day.month, 1))
        if last_year_total is not None and last_year_same is not None:
            rolling.append((day, value + last_year_total - last_year_same))
    return month, rolling
