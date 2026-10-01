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

        # Ключевая ставка текущего года — один запрос к ЦБ. Оценка на графике
        # считается по ставке каждого дня, и без этого после очередного решения
        # ЦБ новый отрезок не появился бы до ручной загрузки.
        from app.services.market.key_rate_service import refresh_current_year

        days = refresh_current_year(db)
        logger.info("Ключевая ставка обновлена: %d дней текущего года", days)

        # Доходность 10-летних ОФЗ за сегодня — безрисковая ставка для оценки
        # на графике. Тоже один запрос.
        from app.services.market.ofz_service import refresh_today

        if refresh_today(db):
            logger.info("Кривая ОФЗ обновлена")
        # Средняя за месяц в карточке требует всех торговых дней месяца —
        # докачиваем пропуски (обычно ноль запросов).
        from app.services.market.ofz_service import load_recent

        filled = load_recent(db)
        if filled:
            logger.info("Кривая ОФЗ: докачано %d дней за месяц", filled)

        # Индексы для раздела «Рынок»: IMOEX, MCFTR, RGBI — по запросу на индекс.
        from app.services.market.index_service import refresh_all as refresh_indices

        logger.info("Индексы обновлены: %d строк", refresh_indices(db))

        # Дивидендные отсечки и сплиты — засечки на графике цены.
        from app.services.market.corporate_events_service import refresh_all

        logger.info("События по бумагам обновлены: %d строк", refresh_all(db))
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

    # Еженедельный listing e-disclosure (вс 03:00 МСК)
    _scheduler.add_job(
        _weekly_disclosure_sync,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="Europe/Moscow"),
        id="weekly_disclosure_sync",
        replace_existing=True,
    )

    # Истёкшие сессии и ссылки — раз в час: сведения о входе не храним дольше сессии.
    _scheduler.add_job(
        _purge_auth,
        CronTrigger(minute=17, timezone="Europe/Moscow"),
        id="purge_auth",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Планировщик запущен. Следующее обновление цен: %s",
        _scheduler.get_job("daily_price_update").next_run_time,
    )


def _weekly_disclosure_sync() -> None:
    """Listing e-disclosure → disclosure_periods (без скачивания/парсинга)."""
    from app.services.disclosure.sync_service import is_sync_alive, start_sync

    if is_sync_alive():
        logger.warning("Планировщик: disclosure sync уже выполняется — пропуск")
        return
    db = SessionLocal()
    try:
        run = start_sync(db)
        logger.info("Планировщик: запущен disclosure sync #%s", run.id)
    except Exception as e:
        logger.error("Планировщик: не удалось стартовать disclosure sync: %s", e)
    finally:
        db.close()


def _purge_auth() -> None:
    from app.services.auth import purge_expired

    db = SessionLocal()
    try:
        sessions, tokens = purge_expired(db)
        if sessions or tokens:
            logger.info("Планировщик: удалено истёкших сессий %s, ссылок %s", sessions, tokens)
    except Exception as e:
        logger.error("Планировщик: чистка сессий не удалась: %s", e)
    finally:
        db.close()


def stop_scheduler() -> None:
    """Останавливает планировщик. Вызывается при завершении приложения."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Планировщик остановлен")
    _scheduler = None
