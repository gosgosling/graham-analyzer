"""
Сервис получения рыночных цен через T-Invest API (бывший Tinkoff Invest API).

Используется эндпоинт MarketDataService/GetLastPrices для получения
последней известной цены по FIGI инструмента.

Цены из API возвращаются в формате {units, nano}:
  price = units + nano / 1_000_000_000
"""
import requests
import logging
from datetime import date, datetime, timezone
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.models.company import Company
from app.models.stock_price import StockPrice

logger = logging.getLogger(__name__)

TINVEST_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"


def _parse_tinvest_price(price_dict: dict) -> Optional[float]:
    """Конвертирует формат {units, nano} в float."""
    if not price_dict:
        return None
    try:
        units = int(price_dict.get("units", 0))
        nano = int(price_dict.get("nano", 0))
        value = units + nano / 1_000_000_000
        return round(value, 4) if value > 0 else None
    except (TypeError, ValueError):
        return None


def get_last_prices(figis: List[str]) -> Dict[str, Optional[float]]:
    """
    Получает последние цены для списка FIGI из T-Invest API.

    Args:
        figis: Список FIGI инструментов (не более 3000 за раз по документации API)

    Returns:
        Словарь {figi: price}. Если цена недоступна — значение None.
    """
    token = settings.TINKOFF_TOKEN
    if not token or token == "your_token_here":
        logger.warning("TINKOFF_TOKEN не настроен — получение цен недоступно")
        return {}

    url = f"{TINVEST_BASE_URL}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetLastPrices"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
    }
    payload = {"figi": figis}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()

        result: Dict[str, Optional[float]] = {}
        for lp in data.get("lastPrices", []):
            figi = lp.get("figi")
            price = _parse_tinvest_price(lp.get("price"))
            if figi:
                result[figi] = price

        logger.info("Получено цен от T-Invest API: %d из %d запрошенных", len(result), len(figis))
        return result

    except requests.exceptions.HTTPError as e:
        logger.error("T-Invest API HTTP ошибка: %s — %s", e.response.status_code, e.response.text)
        return {}
    except requests.exceptions.RequestException as e:
        logger.error("T-Invest API ошибка соединения: %s", e)
        return {}


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
    price = get_last_price(company.figi)
    if price is None:
        logger.warning("Не удалось получить цену для %s (%s)", company.ticker, company.figi)
        return None

    now = datetime.now(timezone.utc)
    today = now.date()

    # Обновляем поля в модели Company
    company.current_price = price  # type: ignore
    company.price_updated_at = now  # type: ignore

    # Upsert в stock_prices (один раз в день)
    _upsert_stock_price(db, company_id=company.id, price_date=today, price=price)

    db.commit()
    db.refresh(company)

    logger.info("Цена %s обновлена: %.4f", company.ticker, price)
    return price


def _upsert_stock_price(
    db: Session, company_id: int, price_date: date, price: float
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
    else:
        db.add(
            StockPrice(
                company_id=company_id,
                date=price_date,
                price=price,
                source="tinvest",
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

    figi_to_company = {c.figi: c for c in companies}
    prices = get_last_prices(list(figi_to_company.keys()))

    now = datetime.now(timezone.utc)
    today = now.date()
    result: Dict[str, Optional[float]] = {}

    for figi, price in prices.items():
        company = figi_to_company.get(figi)
        if company is None:
            continue

        if price is not None:
            company.current_price = price  # type: ignore
            company.price_updated_at = now  # type: ignore
            _upsert_stock_price(db, company_id=company.id, price_date=today, price=price)

        result[company.ticker] = price

    db.commit()
    logger.info("Обновлено цен компаний: %d", sum(1 for v in result.values() if v is not None))
    return result
