import requests
import os
from typing import List, Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

# Определяем путь к корню проекта (на два уровня выше от этого файла)
# backend/app/utils/tinkoff_client.py -> graham-analyzer/
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = BASE_DIR / '.env'

# Загружаем переменные окружения из .env файла в корне проекта
load_dotenv(dotenv_path=ENV_FILE)

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

