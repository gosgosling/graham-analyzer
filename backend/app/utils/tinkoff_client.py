import re
import requests
import os
import time
from typing import List, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

# Определяем путь к корню проекта (на два уровня выше от этого файла)
# backend/app/utils/tinkoff_client.py -> graham-analyzer/
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / '.env'

# Загружаем переменные окружения из .env файла в корне проекта
load_dotenv(dotenv_path=ENV_FILE)

# CDN логотипов эмитентов (используется в приложениях Т-Банка)
BRAND_CDN_BASE = "https://invest-brands.cdn-tinkoff.ru"

# Имя файла без расширения → CDN ожидает суффикс размера, напр. {ISIN}x160.png
_IMG_EXT_RE = re.compile(r"\.(png|webp|jpg|jpeg|svg)(\?.*)?$", re.IGNORECASE)


def _cdn_logo_url_from_logo_name(logo_name: str) -> str:
    """Собирает полный URL логотипа на CDN Т-Банка."""
    ln = str(logo_name).strip()
    if not ln:
        return ""
    low = ln.lower()
    if low.startswith("http://") or low.startswith("https://"):
        path = ln.split("?", 1)[0]
        if _IMG_EXT_RE.search(path):
            return ln
        if "invest-brands.cdn-tinkoff.ru" in low:
            return ln.rstrip("/") + "x160.png" + (f"?{ln.split('?', 1)[1]}" if "?" in ln else "")
        return ln
    path = ln.lstrip("/")
    if not _IMG_EXT_RE.search(path):
        path = f"{path}x160.png"
    return f"{BRAND_CDN_BASE}/{path}"


def _logo_cdn_urls_for_sync(isin: Optional[str], ticker: Optional[str]) -> list[str]:
    """
    Кандидаты URL на invest-brands.cdn-tinkoff.ru (см. investAPI #135).

    Префы (SBERP и т.п.): на CDN логотип часто лежит по тикеру «обычных» акций (SBER),
    а не префа — поэтому сначала base-тикер без финального P, затем ISIN, затем как есть.
    """
    seen: set[str] = set()
    out: list[str] = []

    def push(u: str) -> None:
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    t_up: Optional[str] = None
    if ticker:
        t = str(ticker).strip().upper()
        if t and re.match(r"^[A-Z0-9._-]{1,20}$", t):
            t_up = t
            # SBERP → SBER, GAZPP → GAZP (длина ≥ 5 и оканчивается на P)
            if len(t) >= 5 and t.endswith("P"):
                base = t[:-1]
                if base and re.match(r"^[A-Z0-9._-]{2,19}$", base):
                    push(f"{BRAND_CDN_BASE}/{base}x160.png")
                    push(f"{BRAND_CDN_BASE}/{base}x640.png")

    if isin:
        s = str(isin).strip().upper()
        if s and re.match(r"^[A-Z0-9]{4,}$", s):
            push(f"{BRAND_CDN_BASE}/{s}x160.png")
            push(f"{BRAND_CDN_BASE}/{s}x640.png")

    if t_up:
        push(f"{BRAND_CDN_BASE}/{t_up}x160.png")
        push(f"{BRAND_CDN_BASE}/{t_up}x640.png")

    return out


def fallback_brand_logo_url(isin: Optional[str], ticker: Optional[str]) -> Optional[str]:
    """Первый кандидат для записи в БД (остальные перебирает фронт при загрузке img)."""
    urls = _logo_cdn_urls_for_sync(isin, ticker)
    return urls[0] if urls else None


def extract_brand_from_instrument(instrument: dict) -> tuple[Optional[str], Optional[str]]:
    """
    Извлекает URL логотипа и основной цвет бренда из объекта акции в ответе Shares.

    В REST API поле обычно приходит как вложенный объект brand:
      { "logoName": "xxx.png", "logoBaseColor": "#RRGGBB", "textColor": "..." }
    """
    brand = instrument.get("brand") or instrument.get("Brand")
    logo_name: Optional[str] = None
    color_raw: Optional[str] = None

    if isinstance(brand, dict):
        logo_name = (
            brand.get("logoName")
            or brand.get("logo_name")
            or brand.get("logoFileName")
            or brand.get("logo_file_name")
        )
        color_raw = (
            brand.get("logoBaseColor")
            or brand.get("logo_base_color")
            or brand.get("textColor")
            or brand.get("text_color")
        )
        # Полный URI, если API отдаёт готовую ссылку
        logo_uri = brand.get("logoUri") or brand.get("logo_uri") or brand.get("logoURL") or brand.get("logoUrl")
        if logo_uri and str(logo_uri).strip().lower().startswith("http"):
            lu = str(logo_uri).strip()
            if "invest-brands.cdn-tinkoff.ru" in lu.lower():
                lu = _cdn_logo_url_from_logo_name(lu)
            return lu, _normalize_brand_color(color_raw)

    if not logo_name:
        logo_name = instrument.get("brandLogoName") or instrument.get("logoName")
    if not color_raw:
        color_raw = instrument.get("brandLogoBaseColor") or instrument.get("logoBaseColor")

    logo_url: Optional[str] = None
    if logo_name:
        logo_url = _cdn_logo_url_from_logo_name(str(logo_name))

    return (logo_url or None), _normalize_brand_color(color_raw)


def _normalize_brand_color(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.startswith("#"):
        if len(s) in (4, 7, 9):
            return s.upper()
        return s
    # Иногда приходит "RRGGBB" без #
    if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
        return "#" + s.upper()
    return s


def fetch_share_instrument_by_figi(token: str, base_url: str, figi: str) -> Optional[dict]:
    """
    Детальная карточка акции по FIGI — в ответе часто есть brand (лого, цвет),
    тогда как в массиве Shares эти поля могут отсутствовать.
    """
    if not figi:
        return None
    url = f"{base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/ShareBy"
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
    }
    payload = {"idType": "INSTRUMENT_ID_TYPE_FIGI", "id": figi}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException:
        return None

    if not isinstance(data, dict):
        return None

    def _pick_inst(d: dict) -> Optional[dict]:
        for key in ("instrument", "share"):
            v = d.get(key)
            if isinstance(v, dict) and v.get("figi"):
                return v
        pl = d.get("payload")
        if isinstance(pl, dict):
            for key in ("instrument", "share"):
                v = pl.get(key)
                if isinstance(v, dict) and v.get("figi"):
                    return v
        res = d.get("result")
        if isinstance(res, dict):
            for key in ("instrument", "share"):
                v = res.get(key)
                if isinstance(v, dict) and v.get("figi"):
                    return v
        if d.get("figi") and d.get("ticker"):
            return d
        return None

    return _pick_inst(data)


def get_tinkoff_companies() -> List[Dict]:
    """
    Получает список компаний из T Invest API (Tinkoff Invest API).
    Фильтрует только российские компании или торгующие на Московской бирже.
    Требуется токен TINKOFF_TOKEN в переменных окружения.
    
    Критерии фильтрации:
    - ISIN начинается с "RU" (российская регистрация)
    - Страна риска - Россия
    - Торгуется на Московской бирже (MOEX)
    - Валюта - RUB
    
    Returns:
        Список словарей с информацией о российских компаниях
    """
    token = os.getenv('TINKOFF_TOKEN')
    
    # Диагностика: проверяем, загрузился ли токен
    if not token:
        print(f"ОШИБКА: TINKOFF_TOKEN не найден!")
        print(f"Путь к .env файлу: {ENV_FILE}")
        print(f"Файл .env существует: {ENV_FILE.exists()}")
        if ENV_FILE.exists():
            print(f"Содержимое .env (первые 200 символов): {ENV_FILE.read_text()[:200]}")
        return []
    
    if token == 'token':
        print("Предупреждение: TINKOFF_TOKEN установлен в значение по умолчанию 'your_token_here'")
        return []
    
    # Убираем пробелы и переносы строк из токена (на случай, если они есть)
    token = token.strip()
    
    # Базовый URL T Invest API (новый формат)
    base_url = "https://invest-public-api.tinkoff.ru/rest"
    
    # Эндпоинт для получения инструментов (акций)
    # Используем правильный формат для T Invest API
    url = f"{base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Параметры запроса для получения активных акций
    payload = {
        "instrument_status": "INSTRUMENT_STATUS_BASE"  # Только активные инструменты
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Логируем структуру ответа для диагностики (можно убрать после отладки)
        print(f"Получен ответ от T Invest API. Ключи в ответе: {list(data.keys()) if isinstance(data, dict) else 'не словарь'}")
        
        # Обработка ответа T Invest API
        # Структура ответа может быть разной в зависимости от версии API
        companies = []
        
        # Проверяем разные возможные структуры ответа
        instruments = None
        if isinstance(data, dict):
            if 'instruments' in data:
                instruments = data['instruments']
            elif 'payload' in data:
                if isinstance(data['payload'], dict) and 'instruments' in data['payload']:
                    instruments = data['payload']['instruments']
                elif isinstance(data['payload'], list):
                    instruments = data['payload']
            elif 'result' in data:
                instruments = data['result'].get('instruments') if isinstance(data['result'], dict) else data['result']
        elif isinstance(data, list):
            instruments = data
        
        if instruments:
            print(f"Найдено инструментов: {len(instruments)}")
            filtered_count = 0
            skipped_count = 0
            
            for instrument in instruments:
                
                # Обрабатываем разные форматы данных
                if isinstance(instrument, dict):
                    company = {
                        'figi': instrument.get('figi') or instrument.get('FIGI') or '',
                        'ticker': instrument.get('ticker') or instrument.get('TICKER') or '',
                        'name': instrument.get('name') or instrument.get('NAME') or '',
                        'isin': instrument.get('isin') or instrument.get('ISIN'),
                        'sector': instrument.get('sector') or instrument.get('SECTOR'),
                        'currency': instrument.get('currency') or instrument.get('CURRENCY') or 'RUB',
                        'lot': instrument.get('lot') or instrument.get('LOT') or 1,
                        'api_trade_available_flag': instrument.get('apiTradeAvailableFlag') or instrument.get('api_trade_available_flag') or False,
                        # Дополнительные поля для фильтрации
                        'country_of_risk': instrument.get('countryOfRisk') or instrument.get('country_of_risk') or instrument.get('COUNTRY_OF_RISK'),
                        'exchange': instrument.get('exchange') or instrument.get('EXCHANGE'),
                    }
                    # Фильтруем только валидные записи
                    if not (company['figi'] and company['ticker']):
                        skipped_count += 1
                        continue
                    
                    # Фильтрация: только российские компании или торгующие на Мосбирже
                    is_russian = False
                    is_moex = False
                    
                    # Проверка 1: ISIN начинается с "RU" (российская регистрация)
                    if company['isin']:
                        isin_upper = str(company['isin']).upper()
                        is_russian = isin_upper.startswith('RU')
                    
                    # Проверка 2: Страна риска - Россия
                    if company['country_of_risk']:
                        country = str(company['country_of_risk']).upper()
                        is_russian = is_russian or 'RU' in country or 'RUS' in country or 'RUSSIA' in country or country == 'RU'
                    
                    # Проверка 3: Торгуется на Московской бирже
                    if company['exchange']:
                        exchange = str(company['exchange']).upper()
                        is_moex = 'MOEX' in exchange or 'MOSCOW' in exchange or 'MCX' in exchange or 'MOEX' == exchange
                    
                    # Проверка 4: Валюта RUB также может указывать на российские компании
                    if company['currency'] and str(company['currency']).upper() == 'RUB':
                        is_russian = True
                    
                    # Добавляем только если компания российская ИЛИ торгуется на Мосбирже
                    if is_russian or is_moex:
                        logo_url, brand_color = extract_brand_from_instrument(instrument)
                        # В списке Shares часто нет brand — догружаем ShareBy (с небольшой паузой)
                        if not logo_url or not brand_color:
                            full = fetch_share_instrument_by_figi(token, base_url, company["figi"])
                            if isinstance(full, dict):
                                lu, bc = extract_brand_from_instrument(full)
                                logo_url = logo_url or lu
                                brand_color = brand_color or bc
                            time.sleep(0.02)
                        if not logo_url:
                            logo_url = fallback_brand_logo_url(
                                company.get("isin"), company.get("ticker")
                            )
                        company["brand_logo_url"] = logo_url
                        company["brand_color"] = brand_color
                        companies.append(company)
                        filtered_count += 1
                    else:
                        skipped_count += 1
                        
            print(f"Отфильтровано российских/Мосбиржа: {filtered_count}, пропущено: {skipped_count}")
        else:
            print(f"Не удалось найти инструменты в ответе. Структура данных: {type(data)}")
            if isinstance(data, dict):
                print(f"Доступные ключи: {list(data.keys())}")
        
        print(f"Обработано компаний: {len(companies)}")
        return companies
        
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к T Invest API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Статус: {e.response.status_code}")
            print(f"Ответ: {e.response.text}")
            # Попробуем распарсить JSON ответ для лучшей диагностики
            try:
                error_data = e.response.json()
                print(f"Детали ошибки: {error_data}")
            except:
                pass
        return []

