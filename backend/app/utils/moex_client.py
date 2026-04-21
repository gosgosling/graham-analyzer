import requests
from datetime import date, timedelta
from typing import List, Dict, Optional, Tuple


# ─── Список активных инструментов ─────────────────────────────────────────────

def get_moex_securities() -> List[Dict]:
    """
    Получает список акций компаний, торгующих на Мосбирже.
    Фильтрует только акции (INSTRID='EQIN', SECTYPE='1').
    """
    url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json"

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()

        data = response.json()

        securities = data.get('securities', {})
        columns = securities.get('columns', [])
        rows = securities.get('data', [])

        instrid_idx = columns.index('INSTRID') if 'INSTRID' in columns else None
        sectype_idx = columns.index('SECTYPE') if 'SECTYPE' in columns else None

        companies = []
        for row in rows:
            is_stock = False
            if instrid_idx is not None and row[instrid_idx] == 'EQIN':
                is_stock = True
            elif sectype_idx is not None and row[sectype_idx] == '1':
                is_stock = True

            if not is_stock:
                continue

            company = dict(zip(columns, row))
            normalized_company = {k.lower(): v for k, v in company.items()}
            companies.append(normalized_company)

        return companies

    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к MOEX API: {e}")
        return []


# ─── Дивиденды ────────────────────────────────────────────────────────────────

def _quarter_date_range(fiscal_year: int, fiscal_quarter: int):
    """Возвращает (from_date, till_date) для квартала."""
    starts = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}
    ends   = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    m_s, d_s = starts[fiscal_quarter]
    m_e, d_e = ends[fiscal_quarter]
    return (
        date(fiscal_year, m_s, d_s),
        date(fiscal_year, m_e, d_e),
    )


def get_dividends_for_period(
    ticker: str,
    fiscal_year: int,
    period_type: str = "annual",
    fiscal_quarter: Optional[int] = None,
) -> Optional[Dict]:
    """
    Возвращает дивиденды по тикеру за указанный отчётный период.

    Логика фильтрации: берутся выплаты, у которых `registryclosedate`
    (дата закрытия реестра) попадает в период отчёта.

    Для **годовых отчётов**: все выплаты за указанный calendar year.
    Для **квартальных отчётов**: выплаты за соответствующий квартал
      (российские компании платят дивиденды обычно 1-2 раза в год,
       поэтому за квартальный период может не быть выплат — это нормально).

    Args:
        ticker:          Тикер (SECID), например "LKOH"
        fiscal_year:     Финансовый год
        period_type:     "annual" | "quarterly" | "semi_annual"
        fiscal_quarter:  1-4 (только для quarterly)

    Returns:
        {
            "ticker": str,
            "total": float,          # суммарные дивиденды на акцию за период
            "currency": str,         # валюта (RUB)
            "payments": list[dict],  # детальный список выплат
            "period_from": str,      # начало периода (YYYY-MM-DD)
            "period_till": str,      # конец периода
        }
        или None если MOEX вернул ошибку.
        Если выплат не найдено — total=0, payments=[].
    """
    # Определяем границы периода
    if period_type == "annual":
        period_from = date(fiscal_year, 1, 1)
        period_till = date(fiscal_year, 12, 31)
    elif period_type == "quarterly" and fiscal_quarter:
        period_from, period_till = _quarter_date_range(fiscal_year, fiscal_quarter)
    elif period_type == "semi_annual":
        # Полугодовой: H1 = Q1+Q2, H2 = Q3+Q4
        # Считаем как весь год — пользователь уточнит
        period_from = date(fiscal_year, 1, 1)
        period_till = date(fiscal_year, 12, 31)
    else:
        period_from = date(fiscal_year, 1, 1)
        period_till = date(fiscal_year, 12, 31)

    url = f"https://iss.moex.com/iss/securities/{ticker}/dividends.json"
    try:
        resp = requests.get(url, params={"iss.meta": "off"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return None

    columns = data.get("dividends", {}).get("columns", [])
    rows    = data.get("dividends", {}).get("data", [])

    if not columns:
        return None

    date_idx     = columns.index("registryclosedate") if "registryclosedate" in columns else None
    value_idx    = columns.index("value")             if "value"             in columns else None
    currency_idx = columns.index("currencyid")        if "currencyid"        in columns else None

    if date_idx is None or value_idx is None:
        return None

    payments = []
    for row in rows:
        raw_date = row[date_idx]
        if not raw_date:
            continue
        try:
            record_date = date.fromisoformat(raw_date)
        except ValueError:
            continue

        if period_from <= record_date <= period_till:
            value = row[value_idx]
            currency = row[currency_idx] if currency_idx is not None else "RUB"
            if value is not None:
                payments.append({
                    "registryclosedate": raw_date,
                    "value": float(value),
                    "currency": currency,
                })

    total = round(sum(p["value"] for p in payments), 4)
    primary_currency = payments[0]["currency"] if payments else "RUB"

    return {
        "ticker": ticker,
        "total": total,
        "currency": primary_currency,
        "payments": payments,
        "period_from": period_from.isoformat(),
        "period_till": period_till.isoformat(),
    }


# ─── Количество акций (ISSUESIZE) ─────────────────────────────────────────────

def get_shares_outstanding(ticker: str) -> Optional[Dict]:
    """
    Возвращает количество выпущенных акций (ISSUESIZE) из реестра Мосбиржи.

    ⚠️ Это текущее значение из реестра MOEX, не историческое.
    Для большинства компаний меняется редко, поэтому подходит для заполнения
    поля при вводе отчёта. Если данные недоступны — возвращает None.

    Args:
        ticker: Тикер (SECID) на Мосбирже, например "SBER"

    Returns:
        {"issuesize": int, "secname": str, "lotsize": int, "ticker": str, "board": str}
        или None если тикер не найден.
    """
    for board in _BOARDS:
        url = (
            f"https://iss.moex.com/iss/engines/stock/markets/shares"
            f"/boards/{board}/securities/{ticker}.json"
        )
        params = {
            "iss.meta": "off",
            "iss.only": "securities",
            "securities.columns": "SECID,ISSUESIZE,SECNAME,LOTSIZE",
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            columns = data.get("securities", {}).get("columns", [])
            rows = data.get("securities", {}).get("data", [])

            if not rows:
                continue

            row = dict(zip(columns, rows[0]))
            issuesize = row.get("ISSUESIZE")

            if issuesize is None or issuesize == 0:
                continue

            return {
                "issuesize": int(issuesize),
                "secname": row.get("SECNAME", ""),
                "lotsize": int(row.get("LOTSIZE") or 1),
                "ticker": ticker,
                "board": board,
            }

        except requests.exceptions.RequestException:
            continue

    return None


# ─── Историческая цена закрытия ────────────────────────────────────────────────

# Торговые режимы в порядке приоритета (основной рынок первым)
_BOARDS = ["TQBR", "TQBS", "TQNE", "TQNL"]

_HISTORY_URL = (
    "https://iss.moex.com/iss/history/engines/stock/markets/shares"
    "/boards/{board}/securities/{ticker}.json"
)


def _fetch_history(ticker: str, from_date: date, till_date: date, board: str) -> List[Dict]:
    """
    Запрашивает историю торгов по тикеру в заданном режиме и диапазоне дат.

    Возвращает список записей вида:
        {"date": "YYYY-MM-DD", "close": float}
    отсортированных по дате по возрастанию.
    """
    url = _HISTORY_URL.format(board=board, ticker=ticker)
    params = {
        "from": from_date.isoformat(),
        "till": till_date.isoformat(),
        "columns": "TRADEDATE,LEGALCLOSEPRICE,CLOSE",
        "limit": 20,
        "iss.meta": "off",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return []

    history = data.get("history", {})
    columns = history.get("columns", [])
    rows = history.get("data", [])

    if not rows or not columns:
        return []

    date_idx  = columns.index("TRADEDATE")        if "TRADEDATE"        in columns else None
    close_idx = columns.index("LEGALCLOSEPRICE")  if "LEGALCLOSEPRICE"  in columns else None
    if close_idx is None:
        close_idx = columns.index("CLOSE") if "CLOSE" in columns else None

    if date_idx is None or close_idx is None:
        return []

    result = []
    for row in rows:
        price = row[close_idx]
        if price is None:
            continue
        try:
            result.append({"date": row[date_idx], "close": float(price)})
        except (TypeError, ValueError):
            continue

    return result


def get_closing_price_on_or_before(
    ticker: str,
    target_date: date,
    lookback_days: int = 10,
) -> Optional[Dict]:
    """
    Возвращает цену закрытия акции на дату target_date или ближайший
    предыдущий торговый день (биржа закрыта на выходные и праздники).

    Алгоритм:
    1. Запрашивает историю за lookback_days дней до target_date включительно.
    2. Берёт последнюю доступную запись (самую близкую к target_date снизу).
    3. Перебирает режимы торгов TQBR → TQBS → ... до первого успешного.

    Args:
        ticker:        Тикер (SECID) на Мосбирже, например "SBER"
        target_date:   Целевая дата
        lookback_days: Сколько дней назад смотреть при поиске (по умолчанию 10)

    Returns:
        {"price": float, "date": str, "ticker": str, "board": str}
        или None, если цена не найдена.
    """
    from_date = target_date - timedelta(days=lookback_days)

    for board in _BOARDS:
        records = _fetch_history(ticker, from_date, target_date, board)
        if records:
            # Берём последнюю запись — самый близкий к target_date торговый день
            last = records[-1]
            return {
                "price": last["close"],
                "date": last["date"],
                "ticker": ticker,
                "board": board,
            }

    # Не нашли в стандартных режимах — попробуем без привязки к борду
    # (агрегированный запрос по всем доскам)
    try:
        url = (
            f"https://iss.moex.com/iss/history/engines/stock/markets/shares"
            f"/securities/{ticker}.json"
        )
        params = {
            "from": from_date.isoformat(),
            "till": target_date.isoformat(),
            "columns": "TRADEDATE,LEGALCLOSEPRICE,BOARDID",
            "limit": 20,
            "iss.meta": "off",
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        history = data.get("history", {})
        columns = history.get("columns", [])
        rows = history.get("data", [])

        if rows and columns:
            date_idx  = columns.index("TRADEDATE")       if "TRADEDATE"       in columns else None
            price_idx = columns.index("LEGALCLOSEPRICE") if "LEGALCLOSEPRICE" in columns else None
            board_idx = columns.index("BOARDID")         if "BOARDID"         in columns else None

            if date_idx is not None and price_idx is not None:
                candidates = [
                    row for row in rows
                    if row[price_idx] is not None
                ]
                if candidates:
                    last = candidates[-1]
                    return {
                        "price": float(last[price_idx]),
                        "date": last[date_idx],
                        "ticker": ticker,
                        "board": last[board_idx] if board_idx is not None else "?",
                    }
    except requests.exceptions.RequestException:
        pass

    return None


# ─── Курсы валют (USD/RUB, EUR/RUB …) ────────────────────────────────────────
#
# Биржевой курс берём с рынка selt (Система электронных торгов валютой) по
# инструменту USD000UTSTOM (USD_RUB__TOM, расчёты «завтра» — самый ликвидный).
# Это официальный биржевой курс, который Минфин/ЦБ используют как референс.
# Запросы идут через history-эндпоинт с режимом CETS (Central Electronic Trading
# System). Для исторических данных с 2012+ этот источник работает стабильно.

# Инструменты на MOEX для разных валют
_FX_SECIDS = {
    "USD": "USD000UTSTOM",
    "EUR": "EUR_RUB__TOM",
    "CNY": "CNYRUB_TOM",
}

_FX_HISTORY_URL = (
    "https://iss.moex.com/iss/history/engines/currency/markets/selt"
    "/boards/CETS/securities/{secid}.json"
)


def _fetch_fx_history(secid: str, from_date: date, till_date: date) -> List[Dict]:
    """
    Запрашивает историю курса валюты (WAPRICE / CLOSE) в режиме CETS за диапазон.
    Возвращает список {"date": "YYYY-MM-DD", "rate": float}.
    """
    url = _FX_HISTORY_URL.format(secid=secid)
    params = {
        "from": from_date.isoformat(),
        "till": till_date.isoformat(),
        # WAPRICE (средневзвешенная) — устойчивый показатель биржевого курса;
        # CLOSE может отсутствовать на ранних датах, поэтому берём оба и потом
        # выбираем доступное.
        "columns": "TRADEDATE,WAPRICE,CLOSE,NUMTRADES",
        "limit": 20,
        "iss.meta": "off",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        return []

    history = data.get("history", {})
    columns = history.get("columns", [])
    rows = history.get("data", [])
    if not columns or not rows:
        return []

    date_idx = columns.index("TRADEDATE") if "TRADEDATE" in columns else None
    wap_idx = columns.index("WAPRICE") if "WAPRICE" in columns else None
    close_idx = columns.index("CLOSE") if "CLOSE" in columns else None

    if date_idx is None:
        return []

    out: List[Dict] = []
    for row in rows:
        # Берём WAPRICE, если нет — CLOSE. Это самое надёжное значение курса.
        raw_rate = None
        if wap_idx is not None and row[wap_idx] is not None:
            raw_rate = row[wap_idx]
        elif close_idx is not None and row[close_idx] is not None:
            raw_rate = row[close_idx]
        if raw_rate is None:
            continue
        try:
            out.append({"date": row[date_idx], "rate": float(raw_rate)})
        except (TypeError, ValueError):
            continue
    return out


# ЦБ РФ: официальный курс (публикуется каждый рабочий день). Используется как
# fallback для MOEX, который с июня 2024 прекратил торги USD/EUR.
# XML-формат, document: https://www.cbr.ru/development/SXML/
_CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"

# Числовые коды валют по ISO 4217, которые ЦБ РФ публикует в XML_daily.
_CBR_ISO_CODES = {
    "USD": "R01235",
    "EUR": "R01239",
    "CNY": "R01375",
    "GBP": "R01035",
    "JPY": "R01820",
    "CHF": "R01775",
}


def _fetch_cbr_rate(currency: str, target_date: date) -> Optional[Dict]:
    """
    Возвращает официальный курс ЦБ РФ на `target_date` или предыдущий рабочий
    день (ЦБ по выходным и праздникам курс не устанавливает — возвращает данные
    последнего рабочего дня).

    Возвращает `{"rate": float, "date": "YYYY-MM-DD", "source": "CBR"}`
    или None, если валюта не поддерживается или сеть не ответила.
    """
    currency_upper = currency.upper()
    cbr_id = _CBR_ISO_CODES.get(currency_upper)
    if not cbr_id:
        return None

    # ЦБ принимает дату в формате DD/MM/YYYY.
    params = {"date_req": target_date.strftime("%d/%m/%Y")}
    try:
        resp = requests.get(_CBR_DAILY_URL, params=params, timeout=10)
        resp.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    # Парсим XML. ЦБ возвращает в кодировке windows-1251; requests по content-type
    # корректно декодирует в str (response.text). Избегаем lxml — достаточно
    # stdlib ElementTree. Формат:
    #   <ValCurs Date="31.12.2024" name="Foreign Currency Market">
    #     <Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode>
    #       <Nominal>1</Nominal><Value>101,6797</Value><VunitRate>101,6797</VunitRate>
    #     </Valute>
    #     ...
    #   </ValCurs>
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return None

    actual_date = root.attrib.get("Date", target_date.strftime("%d.%m.%Y"))

    for node in root.findall("Valute"):
        if node.attrib.get("ID") != cbr_id:
            continue
        value_raw = (node.findtext("VunitRate") or node.findtext("Value") or "").strip()
        nominal_raw = (node.findtext("Nominal") or "1").strip()
        if not value_raw:
            return None
        try:
            # В XML разделитель дробной части — запятая.
            value = float(value_raw.replace(",", "."))
            nominal = float(nominal_raw.replace(",", ".")) or 1.0
            # VunitRate уже нормализован на 1 единицу, но если мы взяли Value —
            # поделим на номинал (для JPY/KRW там 100, для USD — 1).
            rate = value if node.findtext("VunitRate") else (value / nominal)
        except ValueError:
            return None
        # Преобразуем DD.MM.YYYY → YYYY-MM-DD для единообразия.
        try:
            d_parts = actual_date.split(".")
            iso_date = f"{d_parts[2]}-{d_parts[1]}-{d_parts[0]}"
        except (IndexError, ValueError):
            iso_date = actual_date
        return {"rate": rate, "date": iso_date, "source": "CBR"}

    return None


def get_fx_rate_on_or_before(
    currency: str,
    target_date: date,
    lookback_days: int = 10,
) -> Optional[Dict]:
    """
    Возвращает курс иностранной валюты к рублю на `target_date`
    или ближайший предыдущий рабочий день.

    Источники (в порядке приоритета):
    1. **MOEX** (рынок selt / CETS) — биржевой курс по инструменту USD000UTSTOM.
       Работает для исторических дат 2012..июнь-2024.
    2. **ЦБ РФ** (XML_daily) — официальный курс, публикуемый ежедневно.
       Используется как fallback, если MOEX не вернул данные (актуально после
       июня 2024, когда MOEX прекратил торги USD/EUR).

    Args:
        currency:     "USD" | "EUR" | "CNY" | "GBP" | "JPY" | "CHF"
        target_date:  Целевая дата (обычно report_date / filing_date отчёта)
        lookback_days: Сколько дней назад искать, если в target_date биржа
                      и ЦБ не работали (длинные праздники).

    Returns:
        {"rate": float, "date": str, "currency": str,
         "source": "MOEX" | "CBR", "secid": str (для MOEX)}
        или None, если курс не найден ни в одном источнике.
    """
    currency_upper = currency.upper()

    # 1) MOEX
    secid = _FX_SECIDS.get(currency_upper)
    if secid:
        from_date = target_date - timedelta(days=lookback_days)
        records = _fetch_fx_history(secid, from_date, target_date)
        if records:
            last = records[-1]
            if last.get("rate") and last["rate"] > 0:
                return {
                    "rate": last["rate"],
                    "date": last["date"],
                    "currency": currency_upper,
                    "source": "MOEX",
                    "secid": secid,
                }

    # 2) Fallback: ЦБ РФ. Идём от target_date вниз, пока не найдём рабочий день.
    for offset in range(lookback_days + 1):
        probe = target_date - timedelta(days=offset)
        cbr = _fetch_cbr_rate(currency_upper, probe)
        if cbr is None:
            continue
        # ЦБ в выходные возвращает данные последней рабочей сессии — поэтому
        # уже первая успешная попытка даст нам корректный курс.
        return {
            "rate": cbr["rate"],
            "date": cbr["date"],
            "currency": currency_upper,
            "source": "CBR",
        }

    return None


# ─── Массовая загрузка дневных цен (свечи MOEX) ───────────────────────────────

def get_price_history(
    ticker: str,
    from_date: date,
    till_date: date,
    board: str = "TQBR",
) -> list:
    """
    Загружает дневные цены закрытия для тикера за диапазон дат из MOEX ISS API.

    Использует эндпоинт /candles с interval=24 (дневные свечи).
    Возвращает только торговые дни (выходные и праздники пропускаются автоматически —
    MOEX не отдаёт данные за нерабочие дни).

    Args:
        ticker:    Тикер (SECID), например "NVTK"
        from_date: Начало диапазона (включительно)
        till_date: Конец диапазона (включительно)
        board:     Режим торгов (по умолчанию TQBR — основной рынок)

    Returns:
        Список пар (дата, цена_закрытия), отсортированных по дате.
        Пустой список если данных нет или произошла ошибка.
    """
    url = (
        f"https://iss.moex.com/iss/engines/stock/markets/shares"
        f"/boards/{board}/securities/{ticker}/candles.json"
    )
    params = {
        "from": from_date.isoformat(),
        "till": till_date.isoformat(),
        "interval": 24,        # дневные свечи
        "iss.meta": "off",
    }

    result = []
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        cols = data.get("candles", {}).get("columns", [])
        rows = data.get("candles", {}).get("data", [])

        if not cols or "close" not in cols or "begin" not in cols:
            return result

        close_idx = cols.index("close")
        begin_idx = cols.index("begin")

        for row in rows:
            try:
                raw_dt = row[begin_idx]  # "2024-01-03 00:00:00"
                close_price = row[close_idx]
                if raw_dt and close_price is not None:
                    trade_date = date.fromisoformat(str(raw_dt).split(" ")[0])
                    result.append((trade_date, float(close_price)))
            except (ValueError, TypeError):
                continue

    except requests.exceptions.RequestException:
        pass

    return result
