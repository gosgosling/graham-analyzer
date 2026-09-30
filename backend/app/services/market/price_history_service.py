"""
Сервис истории цен акций.

Логика хранения:
  • Исторические цены (прошлые дни) — MOEX ISS candles API, цена закрытия.
  • Текущая цена (сегодня) — T-Invest API (более актуальна внутри дня).
  • Точка отсчёта для каждой компании — report_date самого раннего отчёта.
    Если отчётов нет — цены не загружаются.

Бэкфилл:
  При старте сервера и по расписанию сервис докачивает пропуски **с обеих
  сторон** хранимого ряда: вперёд — последние дни, назад — историю до даты
  первого отчёта. Пропущенные дни (выходные, праздники) MOEX не возвращает —
  это нормально.

  Раньше докачка шла только вперёд, от последней записи. Пока история цен
  была не нужна, этого хватало; но ряд, начатый однажды с середины, так и
  оставался начатым с середины навсегда — у всех компаний он начинался с
  21 марта 2026 года, и назад его не дотягивало ничто. Для графика и
  обратного теста это означало полгода истории вместо шестнадцати лет.

**Цены хранятся у нас, а не берутся из биржи на лету.** График и оценка
читают только таблицу `stock_prices`; MOEX нужна лишь для того, чтобы её
наполнить. Недоступность биржи ломает докачку новых дней, но не показ.
"""

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.stock_price import StockPrice
from app.services.ticker_history import normalize_former_tickers
from app.utils.moex_client import get_price_history

logger = logging.getLogger(__name__)


# Раньше этого дня история не грузится. Дневных свечей у ISS по большинству
# бумаг раньше нет, а там, где есть, они относятся к другой экономике и
# сравнивать их не с чем: отчётность в базе начинается с 2008 года.
HISTORY_FLOOR = date(2010, 1, 1)

# Насколько первая хранимая дата может отстоять от нужного начала, чтобы ряд
# считался полным. Первый торговый день после даты отчёта не совпадает с ней
# самой: выходные, праздники, каникулы биржи в начале января.
HISTORY_SLACK = timedelta(days=10)


# ── Режимы торгов до унификации ────────────────────────────────────────────
# До 9 июня 2014 года акции на Мосбирже торговались в нескольких режимах, и
# основной TQBR был не у всех. У Башнефти 2012–2013 годы лежат в EQNE, а в
# TQBR её свечи начинаются только с 9 июня 2014-го; у Газпрома — то же самое.
# Запрос по одному TQBR возвращал такой ряд обрезанным ровно по этой дате.
BOARDS_UNIFIED = date(2014, 6, 9)
# Порядок — от более позднего к раннему: TQNE жил с 2013 года до объединения,
# EQBR и EQNE — до перехода на расчёты T+2. День, найденный в раннем режиме,
# не перекрывает день из позднего.
LEGACY_BOARDS = ("TQNE", "EQBR", "EQNE")


def _fetch_history(ticker: str, frm: date, till: date) -> list:
    """Цены за диапазон, с запасными режимами для лет до унификации."""
    rows = list(get_price_history(ticker, frm, till))
    if frm >= BOARDS_UNIFIED:
        return rows

    have = {day for day, _ in rows}
    earliest = min(have) if have else till + timedelta(days=1)
    gap_till = min(earliest - timedelta(days=1), BOARDS_UNIFIED)
    if gap_till - frm <= HISTORY_SLACK:
        return rows

    for board in LEGACY_BOARDS:
        for day, price in get_price_history(ticker, frm, gap_till, board=board):
            if day not in have:
                have.add(day)
                rows.append((day, price))
    rows.sort(key=lambda pair: pair[0])
    return rows


def _ticker_segments(company: Company, frm: date, till: date) -> list:
    """Диапазон, разрезанный по датам переименований: под каким символом искать.

    ISS хранит торги под тем именем, которое бумага носила в тот день, и связи
    между старым и новым символом у биржи нет. Запрос всего диапазона по
    нынешнему тикеру возвращал историю, начинающуюся с даты переименования: у
    X5 цены шли с января 2025-го при отчётах с 2021-го, у Яндекса — с июля
    2024-го. Выглядело это как «биржа столько не хранит», хотя цена всё это
    время лежала под FIVE и YNDX.

    Границы те же, что у `resolve_ticker`: `until` — последний день жизни
    старого символа, следующий день уже принадлежит новому.
    """
    result: list = []
    cursor = frm
    for entry in normalize_former_tickers(company.former_tickers):
        until = date.fromisoformat(entry["until"])
        if until < cursor:
            # Звено кончилось раньше, чем начинается нужный диапазон.
            continue
        segment_till = min(until, till)
        if cursor <= segment_till:
            result.append((entry["ticker"], cursor, segment_till))
        cursor = segment_till + timedelta(days=1)
        if cursor > till:
            return result

    result.append((str(company.ticker), cursor, till))
    return result


def _get_start_date(db: Session, company: Company) -> Optional[date]:
    """
    Возвращает дату начала загрузки цен для компании — report_date самого
    раннего финансового отчёта, но не раньше `HISTORY_FLOOR`.
    Если отчётов нет — None (цены не нужны).
    """
    earliest = (
        db.query(FinancialReport.report_date)
        .filter(FinancialReport.company_id == company.id)
        .order_by(FinancialReport.report_date)
        .first()
    )
    if earliest is None:
        return None
    d = earliest[0]
    if d is None:
        return None
    # Если дата пришла как datetime.date или строка — нормализуем
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return max(d, HISTORY_FLOOR)


def _get_first_stored_date(db: Session, company_id: int) -> Optional[date]:
    """Дата самой ранней записи в stock_prices для компании."""
    row = (
        db.query(StockPrice.date)
        .filter(StockPrice.company_id == company_id)
        .order_by(StockPrice.date)
        .first()
    )
    return row[0] if row else None


def _get_last_stored_date(db: Session, company_id: int) -> Optional[date]:
    """Возвращает дату последней записи в stock_prices для компании."""
    row = (
        db.query(StockPrice.date)
        .filter(StockPrice.company_id == company_id)
        .order_by(StockPrice.date.desc())
        .first()
    )
    return row[0] if row else None


def backfill_company_prices(
    db: Session,
    company: Company,
    force_from: Optional[date] = None,
) -> int:
    """
    Докачивает пропущенные ежедневные цены закрытия для компании из MOEX.

    Определяет диапазоны автоматически, с обеих сторон хранимого ряда:
      • назад — от даты первого отчёта (не раньше HISTORY_FLOOR) до первой
        хранимой записи, если ряд начинается заметно позже;
      • вперёд — от последней записи до вчера (сегодняшний день ещё может
        меняться — берём T-Invest).

    Args:
        db:         Сессия БД
        company:    Объект Company (должен иметь поле ticker)
        force_from: Принудительно задать начало диапазона (для ручного запроса)

    Returns:
        Количество добавленных записей.
    """
    ticker = company.ticker
    yesterday = date.today() - timedelta(days=1)

    # Диапазоны, которые надо докачать. Их бывает два: история назад, если
    # ряд начинается позже первого отчёта, и последние дни вперёд.
    ranges: list = []
    if force_from:
        ranges.append((force_from, yesterday))
    else:
        start_date = _get_start_date(db, company)
        if start_date is None:
            logger.debug("Компания %s: нет отчётов, пропускаем бэкфилл цен", ticker)
            return 0

        first_stored = _get_first_stored_date(db, company.id)
        last_stored = _get_last_stored_date(db, company.id)

        if first_stored is None:
            ranges.append((start_date, yesterday))
        else:
            # Назад. У компании, вышедшей на биржу позже первого отчёта, этот
            # запрос будет повторяться при каждом старте и возвращать пусто —
            # это одна короткая страница, и держать ради неё отметку «история
            # полная» в отдельной таблице дороже, чем её отправить.
            if first_stored - start_date > HISTORY_SLACK:
                ranges.append((start_date, first_stored - timedelta(days=1)))
            if last_stored < yesterday:
                ranges.append((last_stored + timedelta(days=1), yesterday))

    ranges = [(frm, till) for frm, till in ranges if frm <= till]
    if not ranges:
        logger.debug("Компания %s: цены актуальны", ticker)
        return 0

    history: list = []
    for frm, till in ranges:
        for symbol, seg_frm, seg_till in _ticker_segments(company, frm, till):
            logger.info("Бэкфилл цен %s: %s → %s под именем %s",
                        ticker, seg_frm.isoformat(), seg_till.isoformat(), symbol)
            chunk = _fetch_history(symbol, seg_frm, seg_till)
            if not chunk:
                logger.debug("Бэкфилл %s: MOEX не вернул данных за %s–%s (%s)",
                             ticker, seg_frm, seg_till, symbol)
            history.extend(chunk)
    if not history:
        return 0
    from_date = min(frm for frm, _ in ranges)

    # Уже имеющиеся даты берутся одним запросом. Раньше здесь стоял SELECT на
    # каждую точку истории; пока докачивались последние дни, это было незаметно,
    # но на полной истории — четыре тысячи запросов к базе на одну компанию.
    existing = {
        row[0] for row in db.query(StockPrice.date).filter(
            StockPrice.company_id == company.id,
            StockPrice.date >= from_date,
        )
    }

    added = 0
    for trade_date, close_price in history:
        if trade_date in existing:
            continue
        db.add(StockPrice(
            company_id=company.id,
            date=trade_date,
            price=close_price,
            source="moex",
        ))
        existing.add(trade_date)
        added += 1

    if added:
        db.commit()
        logger.info("Бэкфилл %s: добавлено %d записей", ticker, added)

    return added


def backfill_all_companies(db: Session) -> dict:
    """
    Докачивает пропущенные цены для всех компаний, у которых есть отчёты.
    Вызывается при старте сервера и по расписанию.

    Returns:
        Словарь {ticker: количество_добавленных_записей}
    """
    companies = db.query(Company).all()
    result = {}
    for company in companies:
        try:
            added = backfill_company_prices(db, company)
            if added > 0:
                result[company.ticker] = added
        except Exception as e:
            logger.error("Ошибка бэкфилла для %s: %s", company.ticker, e)
    return result
