import requests
from datetime import date, timedelta
from typing import List, Dict, Optional


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
