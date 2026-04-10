"""
Сервис получения облигаций через T-Invest API.

Данные не хранятся в БД — загружаются из API напрямую.
Результат кэшируется в памяти на 5 минут, чтобы не нагружать API
при каждом открытии страницы.
"""
import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent
load_dotenv(dotenv_path=BASE_DIR / '.env')

logger = logging.getLogger(__name__)

TINKOFF_BASE_URL = "https://invest-public-api.tinkoff.ru/rest"
_CACHE_TTL = 300  # секунд

# Простой in-memory кэш: (timestamp, data)
_bonds_cache: tuple[float, List[Dict]] = (0.0, [])


def _get_token() -> Optional[str]:
    token = os.getenv('TINKOFF_TOKEN', '').strip()
    if not token or token.lower() in ('', 'token', 'your_token_here', 'tocken'):
        return None
    return token


def _parse_money_value(v: object) -> Optional[float]:
    """Парсит MoneyValue из T-Invest API: {"units": "1000", "nano": 0}."""
    if isinstance(v, dict):
        units = v.get('units') or 0
        nano = v.get('nano') or 0
        return float(units) + float(nano) / 1_000_000_000
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _parse_date(v: object) -> Optional[str]:
    """Парсит дату из T-Invest API: {"year": 2030, "month": 12, "day": 31} → 'YYYY-MM-DD'."""
    if isinstance(v, dict):
        year = v.get('year') or v.get('Year')
        month = v.get('month') or v.get('Month')
        day = v.get('day') or v.get('Day')
        if year and month and day:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return None


def _instrument_to_bond(inst: dict) -> Optional[Dict]:
    """Преобразует инструмент из T-Invest API в словарь облигации."""
    figi = inst.get('figi', '')
    ticker = inst.get('ticker', '')
    if not (figi and ticker):
        return None

    currency = (inst.get('currency') or '').upper()
    country = (inst.get('countryOfRisk') or inst.get('country_of_risk') or '').upper()
    exchange = (inst.get('exchange') or '').upper()
    isin = (inst.get('isin') or '').upper()

    # Фильтруем только российские/MOEX облигации
    is_russian = isin.startswith('RU') or 'RU' in country or currency == 'RUB'
    is_moex = any(x in exchange for x in ('MOEX', 'MOSCOW', 'MCX'))
    if not (is_russian or is_moex):
        return None

    coupon_qty = inst.get('couponQuantityPerYear') or inst.get('coupon_quantity_per_year')
    if coupon_qty is not None:
        try:
            coupon_qty = int(coupon_qty)
        except (TypeError, ValueError):
            coupon_qty = None

    issue_size = inst.get('issueSize') or inst.get('issue_size')
    if issue_size is not None:
        try:
            issue_size = int(issue_size)
        except (TypeError, ValueError):
            issue_size = None

    return {
        'figi': figi,
        'ticker': ticker,
        'name': inst.get('name') or '',
        'isin': isin,
        'currency': currency or 'RUB',
        'sector': inst.get('sector') or '',
        'country_of_risk': country,
        'exchange': exchange,
        'maturity_date': _parse_date(inst.get('maturityDate') or inst.get('maturity_date')),
        'nominal': _parse_money_value(inst.get('nominal')),
        'coupon_quantity_per_year': coupon_qty,
        'floating_coupon_flag': bool(inst.get('floatingCouponFlag') or inst.get('floating_coupon_flag')),
        'perpetual_flag': bool(inst.get('perpetualFlag') or inst.get('perpetual_flag')),
        'amortization_flag': bool(inst.get('amortizationFlag') or inst.get('amortization_flag')),
        'issue_size': issue_size,
        'lot': int(inst.get('lot') or 1),
        'country_of_risk_name': inst.get('countryOfRiskName') or inst.get('country_of_risk_name') or '',
        'placement_date': _parse_date(inst.get('placementDate') or inst.get('placement_date')),
    }


def _fetch_from_api() -> List[Dict]:
    token = _get_token()
    if not token:
        logger.warning("TINKOFF_TOKEN не настроен — облигации не загружены")
        return []

    url = f"{TINKOFF_BASE_URL}/tinkoff.public.invest.api.contract.v1.InstrumentsService/Bonds"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"instrument_status": "INSTRUMENT_STATUS_BASE"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка T-Invest API (Bonds): {e}")
        return []

    instruments = None
    if isinstance(data, dict):
        instruments = (
            data.get('instruments')
            or (data.get('payload') or {}).get('instruments')
            or (data.get('result') or {}).get('instruments')
        )

    if not instruments:
        logger.warning("T-Invest Bonds: ответ не содержит инструментов")
        return []

    bonds = []
    for inst in instruments:
        if not isinstance(inst, dict):
            continue
        bond = _instrument_to_bond(inst)
        if bond:
            bonds.append(bond)

    logger.info(f"Получено облигаций из T-Invest API: {len(bonds)}")
    return bonds


def get_bonds() -> List[Dict]:
    """Возвращает список облигаций (с кэшированием на 5 минут)."""
    global _bonds_cache
    ts, data = _bonds_cache
    if time.monotonic() - ts < _CACHE_TTL and data:
        return data
    data = _fetch_from_api()
    _bonds_cache = (time.monotonic(), data)
    return data


def get_bond_by_figi(figi: str) -> Optional[Dict]:
    """
    Ищет облигацию по FIGI.
    Сначала проверяет кэш списка, затем делает точечный запрос BondBy.
    """
    # 1. Быстрый поиск в кэше
    _, cached = _bonds_cache
    if cached:
        found = next((b for b in cached if b['figi'] == figi), None)
        if found:
            return found

    # 2. Точечный запрос BondBy
    token = _get_token()
    if not token:
        return None

    url = f"{TINKOFF_BASE_URL}/tinkoff.public.invest.api.contract.v1.InstrumentsService/BondBy"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка BondBy {figi}: {e}")
        return None

    # Извлекаем инструмент из разных структур ответа
    inst = None
    if isinstance(data, dict):
        for key in ('instrument', 'bond'):
            v = data.get(key)
            if isinstance(v, dict) and v.get('figi'):
                inst = v
                break
        if not inst:
            pl = data.get('payload') or data.get('result')
            if isinstance(pl, dict):
                for key in ('instrument', 'bond'):
                    v = pl.get(key)
                    if isinstance(v, dict) and v.get('figi'):
                        inst = v
                        break
        if not inst and data.get('figi'):
            inst = data

    if not inst:
        return None

    # Для BondBy фильтрацию по стране не применяем (пользователь запросил конкретный FIGI)
    bond = _instrument_to_bond(inst)
    if not bond:
        # Если фильтр отсеял — возвращаем без фильтрации
        bond = {
            'figi': inst.get('figi', ''),
            'ticker': inst.get('ticker', ''),
            'name': inst.get('name') or '',
            'isin': (inst.get('isin') or '').upper(),
            'currency': (inst.get('currency') or 'RUB').upper(),
            'sector': inst.get('sector') or '',
            'country_of_risk': (inst.get('countryOfRisk') or '').upper(),
            'exchange': (inst.get('exchange') or '').upper(),
            'maturity_date': _parse_date(inst.get('maturityDate')),
            'nominal': _parse_money_value(inst.get('nominal')),
            'coupon_quantity_per_year': inst.get('couponQuantityPerYear'),
            'floating_coupon_flag': bool(inst.get('floatingCouponFlag')),
            'perpetual_flag': bool(inst.get('perpetualFlag')),
            'amortization_flag': bool(inst.get('amortizationFlag')),
            'issue_size': inst.get('issueSize'),
            'lot': int(inst.get('lot') or 1),
            'country_of_risk_name': inst.get('countryOfRiskName') or '',
            'placement_date': _parse_date(inst.get('placementDate')),
        }
    return bond
