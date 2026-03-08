"""
Сервис истории цен акций.

Логика хранения:
  • Исторические цены (прошлые дни) — MOEX ISS candles API, цена закрытия.
  • Текущая цена (сегодня) — T-Invest API (более актуальна внутри дня).
  • Точка отсчёта для каждой компании — report_date самого раннего отчёта.
    Если отчётов нет — цены не загружаются.

Бэкфилл:
  При старте сервера и по расписанию сервис проверяет дату последней
  записи в stock_prices и докачивает пропущенные торговые дни.
  Пропущенные дни (выходные, праздники) MOEX не возвращает — это нормально.
"""

import logging
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.stock_price import StockPrice
from app.utils.moex_client import get_price_history

logger = logging.getLogger(__name__)


def _get_start_date(db: Session, company: Company) -> Optional[date]:
    """
    Возвращает дату начала загрузки цен для компании —
    report_date самого раннего финансового отчёта.
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
    # Если дата пришла как datetime.date или строка — нормализуем
    if isinstance(d, str):
        return date.fromisoformat(d)
    return d


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

    Определяет диапазон автоматически:
      • from_date = max(дата последней записи + 1, дата первого отчёта)
      • till_date = вчера (сегодняшний день ещё может меняться — берём T-Invest)

    Args:
        db:         Сессия БД
        company:    Объект Company (должен иметь поле ticker)
        force_from: Принудительно задать начало диапазона (для ручного запроса)

    Returns:
        Количество добавленных записей.
    """
    ticker = company.ticker
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Определяем точку отсчёта
    if force_from:
        from_date = force_from
    else:
        start_date = _get_start_date(db, company)
        if start_date is None:
            logger.debug("Компания %s: нет отчётов, пропускаем бэкфилл цен", ticker)
            return 0

        last_stored = _get_last_stored_date(db, company.id)
        if last_stored and last_stored >= yesterday:
            logger.debug("Компания %s: цены актуальны (последняя: %s)", ticker, last_stored)
            return 0

        from_date = (last_stored + timedelta(days=1)) if last_stored else start_date

    if from_date > yesterday:
        return 0

    logger.info(
        "Бэкфилл цен %s: %s → %s",
        ticker, from_date.isoformat(), yesterday.isoformat(),
    )

    history = get_price_history(ticker, from_date, yesterday)
    if not history:
        logger.warning("Бэкфилл %s: MOEX не вернул данных за %s–%s", ticker, from_date, yesterday)
        return 0

    added = 0
    for trade_date, close_price in history:
        # Проверяем дубликат
        exists = (
            db.query(StockPrice.id)
            .filter(
                StockPrice.company_id == company.id,
                StockPrice.date == trade_date,
            )
            .first()
        )
        if not exists:
            db.add(StockPrice(
                company_id=company.id,
                date=trade_date,
                price=close_price,
                source="moex",
            ))
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
