"""
Сервис получения рыночных цен через T-Invest API (бывший Tinkoff Invest API).

Используется эндпоинт MarketDataService/GetLastPrices для получения
последней известной цены по FIGI инструмента.

Цены из API возвращаются в формате {units, nano}:
  price = units + nano / 1_000_000_000

**Резерв — Мосбиржа.** Если T-Invest не ответил или вернул не все бумаги,
недостающие цены берутся из MOEX ISS (`moex_client.get_last_prices`): один
запрос на весь рынок, котировка с задержкой 15 минут. У компании
сохраняется источник (`price_source`) и момент котировки (`price_quoted_at`),
чтобы страница могла сказать, откуда цена и насколько она свежая.

**Внутри дня.** Планировщик зовёт `update_all_company_prices` каждые пять
минут торгового дня. Записываются только изменившиеся цены: если цена та же,
ни строка компании, ни дневная запись не трогаются — версия цен в кэше
расчётов (`data_cache`) не меняется, и тяжёлые ответы не пересчитываются
зря (вечером и в выходные — ни одной записи).

**Предохранитель.** Обращения к T-Invest идут через `source_health.TINVEST`:
после сбоя брокер не опрашивается до конца паузы (1, 2, 4… до 30 минут), и
цены сразу берутся с биржи, без ожидания таймаута.
"""
import requests
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.models.company import Company
from app.models.stock_price import StockPrice
from app.utils.http_session import external_session, tls_hint
from app.utils.source_health import MOEX_LIVE, TINVEST

logger = logging.getLogger(__name__)

TINVEST_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"
MOSCOW = ZoneInfo("Europe/Moscow")


def _parse_tinvest_price(price_dict: dict) -> Optional[float]:
    """Конвертирует формат {units, nano} в float."""
    if not price_dict:
        return None
    try:
        units = int(price_dict.get("units", 0))
        nano = int(price_dict.get("nano", 0))
        value = units + nano / 1_000_000_000
        # Шесть знаков: у копеечных бумаг четвёртый знак — уже потеря процентов.
        return round(value, 6) if value > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: object) -> Optional[datetime]:
    """Время последней сделки из ответа брокера (RFC 3339, UTC)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        # Python до 3.11 не понимает «Z» и наносекунды — режем до микросекунд.
        head, _, frac = value.rstrip("Z").partition(".")
        stamp = datetime.fromisoformat(head + ("." + frac[:6] if frac else ""))
    except ValueError:
        return None
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def get_last_prices(figis: List[str]) -> Dict[str, Optional[float]]:
    """Последние цены по FIGI из T-Invest API. → {figi: цена}."""
    return {figi: quote[0] for figi, quote in get_last_quotes(figis).items()}


def get_last_quotes(figis: List[str]) -> Dict[str, tuple]:
    """
    Последние цены и время сделки для списка FIGI из T-Invest API.

    Args:
        figis: Список FIGI инструментов (не более 3000 за раз по документации API)

    Returns:
        Словарь {figi: (цена, время сделки или None)}. Если цена недоступна —
        цена None.
    """
    token = settings.TINKOFF_TOKEN
    if not token or token == "your_token_here":
        logger.warning("TINKOFF_TOKEN не настроен — получение цен недоступно")
        return {}
    if not TINVEST.available():
        logger.info("T-Invest на паузе после сбоя — цены берутся с Мосбиржи")
        return {}

    url = f"{TINVEST_BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
    }
    payload = {"figi": figis}

    try:
        # Сессия без прокси из окружения и с бандлом сертификатов из настроек —
        # см. app/utils/http_session.py. Таймаут короткий: при недоступном
        # брокере ждать дольше незачем, резерв ответит за секунду.
        response = external_session().post(url, json=payload, headers=headers, timeout=8)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as e:
        logger.error("T-Invest API HTTP ошибка: %s — %s", e.response.status_code, e.response.text[:300])
        # 401/403 — ошибка токена, а не недоступность: паузу не включаем,
        # иначе неверный токен выглядел бы как «брокер лежит».
        if e.response.status_code >= 500 or e.response.status_code == 429:
            TINVEST.failure(f"HTTP {e.response.status_code}")
        return {}
    except (requests.exceptions.RequestException, ValueError) as e:
        hint = tls_hint(e) if isinstance(e, requests.exceptions.RequestException) else None
        if hint:
            logger.error("T-Invest API: %s Исходная ошибка: %s", hint, e)
        else:
            logger.error("T-Invest API ошибка соединения: %s", e)
        TINVEST.failure(e)
        return {}

    TINVEST.success()
    result: Dict[str, tuple] = {}
    for lp in data.get("lastPrices", []):
        figi = lp.get("figi")
        price = _parse_tinvest_price(lp.get("price"))
        if figi:
            result[figi] = (price, _parse_time(lp.get("time")))

    logger.info("Получено цен от T-Invest API: %d из %d запрошенных", len(result), len(figis))
    return result


def get_moex_prices(companies: List[Company]) -> Dict[int, tuple]:
    """Резервные цены с Мосбиржи. → {company_id: (цена, время котировки)}."""
    from app.utils.moex_client import MoexUnavailableError, get_last_prices as moex_last

    if not companies:
        return {}
    if not MOEX_LIVE.available():
        return {}
    try:
        quotes = moex_last([str(c.ticker) for c in companies])
    except MoexUnavailableError as exc:
        logger.error("Мосбиржа: текущие цены не получены: %s", exc)
        MOEX_LIVE.failure(exc)
        return {}
    MOEX_LIVE.success()
    out = {}
    for company in companies:
        quote = quotes.get(str(company.ticker).strip().upper())
        if quote is not None:
            out[company.id] = quote
    logger.info("Резервные цены с Мосбиржи: %d из %d", len(out), len(companies))
    return out


def _apply_price(db: Session, company: Company, price: float, source: str,
                 quoted_at: Optional[datetime], now: datetime) -> bool:
    """Записать цену компании. False — цена та же, ничего не писалось.

    Дневная запись в `stock_prices` датируется днём котировки по Москве, а не
    днём опроса: ночной или субботний опрос с пятничной ценой обновит
    пятницу, а не заведёт лишний день на графике.

    Та же цена из того же источника за тот же день не пишется вовсе: время
    котировки у компании остаётся временем, когда цена стала такой. Без этого
    каждый пятиминутный опрос менял бы строку компании, и кэш расчётов
    пересчитывался бы и вечером, и в выходные.
    """
    quoted = quoted_at or now
    day = quoted.astimezone(MOSCOW).date()
    stored = company.price_quoted_at or company.price_updated_at
    if (
        company.current_price is not None
        and abs(float(company.current_price) - price) < 1e-9
        and company.price_source == source
        and stored is not None
        and _aware(stored).astimezone(MOSCOW).date() == day
    ):
        return False
    company.current_price = price  # type: ignore
    company.price_updated_at = now  # type: ignore
    company.price_source = source  # type: ignore
    company.price_quoted_at = quoted  # type: ignore
    _upsert_stock_price(db, company_id=company.id, price_date=day, price=price, source=source)
    return True


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def get_last_price(figi: str) -> Optional[float]:
    """Получает текущую цену одного инструмента по FIGI."""
    prices = get_last_prices([figi])
    return prices.get(figi)


def update_company_price(db: Session, company: Company) -> Optional[float]:
    """
    Обновляет текущую цену компании из T-Invest API и сохраняет
    дневную запись в таблицу stock_prices.

    Args:
        db: Сессия БД
        company: Объект Company (должен иметь поле figi)

    Returns:
        Обновлённая цена или None если не удалось получить
    """
    now = datetime.now(timezone.utc)
    price, traded_at = get_last_quotes([company.figi]).get(company.figi, (None, None)) \
        if company.figi else (None, None)
    if price is not None:
        _apply_price(db, company, price, "tinvest", traded_at, now)
    else:
        quote = get_moex_prices([company]).get(company.id)
        if quote is None:
            logger.warning("Не удалось получить цену для %s (%s) ни у T-Invest, ни у Мосбиржи",
                           company.ticker, company.figi)
            return None
        price = quote[0]
        _apply_price(db, company, price, "moex", quote[1], now)

    db.commit()
    db.refresh(company)

    logger.info("Цена %s обновлена: %.4f (%s)", company.ticker, price, company.price_source)
    return price


def _upsert_stock_price(
    db: Session, company_id: int, price_date: date, price: float, source: str = "tinvest"
) -> None:
    """
    Создаёт или обновляет запись о цене за указанную дату (upsert).
    Если за сегодня запись уже есть — обновляет цену (на случай нескольких вызовов за день).
    """
    existing = (
        db.query(StockPrice)
        .filter(StockPrice.company_id == company_id, StockPrice.date == price_date)
        .first()
    )
    if existing:
        existing.price = price  # type: ignore
        existing.source = source  # type: ignore
    else:
        db.add(
            StockPrice(
                company_id=company_id,
                date=price_date,
                price=price,
                source=source,
            )
        )


def update_all_company_prices(db: Session) -> Dict[str, Optional[float]]:
    """
    Обновляет цены всех компаний из БД за один вызов к T-Invest API.

    Returns:
        Словарь {ticker: price}
    """
    companies: List[Company] = db.query(Company).all()
    if not companies:
        return {}

    figis = [c.figi for c in companies if c.figi]
    quotes = get_last_quotes(figis) if figis else {}

    now = datetime.now(timezone.utc)
    result: Dict[str, Optional[float]] = {}
    missing: List[Company] = []
    changed = {"tinvest": 0, "moex": 0}

    for company in companies:
        price, traded_at = quotes.get(company.figi, (None, None)) if company.figi else (None, None)
        if price is not None:
            if _apply_price(db, company, price, "tinvest", traded_at, now):
                changed["tinvest"] += 1
            result[company.ticker] = price
        else:
            missing.append(company)

    # Всё, что брокер не дал — или весь список, если он недоступен, — с биржи.
    by_id = {c.id: c for c in missing}
    for company_id, (price, quoted_at) in get_moex_prices(missing).items():
        company = by_id[company_id]
        if _apply_price(db, company, price, "moex", quoted_at, now):
            changed["moex"] += 1
        result[company.ticker] = price
    for company in missing:
        result.setdefault(company.ticker, None)

    db.commit()
    logger.info("Цены компаний: изменилось T-Invest %d, Мосбиржа %d; без цены %d",
                changed["tinvest"], changed["moex"],
                sum(1 for v in result.values() if v is None))
    return result
