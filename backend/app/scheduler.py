"""
Планировщик фоновых задач (APScheduler).

Задачи:
  1. Ежедневно в 19:00 МСК (UTC+3) — обновить текущие цены из T-Invest
     и докачать пропущенные исторические цены из MOEX.
  2. При старте сервера — сразу проверить и закрыть пробелы в ценах.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import SessionLocal

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _daily_price_update() -> None:
    """
    Ежедневная задача:
      1. Бэкфилл — MOEX докачивает все пропущенные дни (в т.ч. если сервер
         был выключен несколько дней).
      2. Текущая цена — T-Invest обновляет сегодняшнее значение.
    """
    from app.services.market.price_history_service import backfill_all_companies
    from app.services.market.tinvest_price_service import update_all_company_prices

    logger.info("Планировщик: запуск ежедневного обновления цен")
    db = SessionLocal()
    try:
        backfill_result = backfill_all_companies(db)
        if backfill_result:
            logger.info("Бэкфилл завершён: %s", backfill_result)

        prices = update_all_company_prices(db)
        updated = sum(1 for v in prices.values() if v is not None)
        logger.info("Текущие цены обновлены: %d компаний", updated)
    except Exception as e:
        logger.error("Ошибка в ежедневном обновлении цен: %s", e)
    finally:
        db.close()


def _startup_backfill() -> None:
    """
    Запускается при старте сервера: докачивает все пропуски в ценах.
    Запускается один раз, через 5 секунд после старта (чтобы не блокировать
    инициализацию FastAPI).
    """
    from app.services.market.price_history_service import backfill_all_companies

    logger.info("Старт сервера: проверка и бэкфилл пропущенных цен")
    db = SessionLocal()
    try:
        result = backfill_all_companies(db)
        if result:
            logger.info("Стартовый бэкфилл завершён: %s", result)
        else:
            logger.info("Стартовый бэкфилл: пробелов не обнаружено")
    except Exception as e:
        logger.error("Ошибка стартового бэкфилла: %s", e)
    finally:
        db.close()


def start_scheduler() -> None:
    """
    Инициализирует и запускает планировщик.
    Вызывается из lifespan FastAPI при старте приложения.
    """
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="Europe/Moscow")

    # Ежедневно в 19:00 МСК (торги на MOEX закрываются в 18:50)
    _scheduler.add_job(
        _daily_price_update,
        CronTrigger(hour=19, minute=0, timezone="Europe/Moscow"),
        id="daily_price_update",
        replace_existing=True,
    )

    # Бэкфилл при старте — через 5 секунд после инициализации
    run_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    _scheduler.add_job(
        _startup_backfill,
        "date",                          # одноразовый запуск
        run_date=run_at,
        id="startup_backfill",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Планировщик запущен. Следующее обновление цен: %s",
        _scheduler.get_job("daily_price_update").next_run_time,
    )


def stop_scheduler() -> None:
    """Останавливает планировщик. Вызывается при завершении приложения."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
    _scheduler = None
