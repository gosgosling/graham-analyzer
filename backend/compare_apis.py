#!/usr/bin/env python3
"""
Скрипт для сравнения данных из MOEX API и T Invest API
Помогает понять различия и что может отсутствовать
"""

import requests
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from collections import defaultdict

# Загружаем переменные окружения
BASE_DIR = Path(__file__).resolve().parent.parent  # Корень проекта (на уровень выше backend)
ENV_FILE = BASE_DIR / '.env'
load_dotenv(dotenv_path=ENV_FILE)

def get_moex_securities():
    """Получает данные из MOEX API"""
    print("\n" + "="*80)
    print("ЗАПРОС К MOEX API")
    print("="*80)
    
    url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        securities = data.get('securities', {})
        columns = securities.get('columns', [])
        rows = securities.get('data', [])
        
        print(f"Колонки в ответе MOEX: {columns}")
        print(f"Всего строк: {len(rows)}")
        
        # Фильтруем только акции
        instrid_idx = columns.index('INSTRID') if 'INSTRID' in columns else None
        sectype_idx = columns.index('SECTYPE') if 'SECTYPE' in columns else None
        
        moex_data = []
        for row in rows:
            is_stock = False
            if instrid_idx is not None and row[instrid_idx] == 'EQIN':
                is_stock = True
            elif sectype_idx is not None and row[sectype_idx] == '1':
                is_stock = True
            
            if is_stock:
                security = dict(zip(columns, row))
                moex_data.append(security)
        
        print(f"Отфильтровано акций: {len(moex_data)}")
        
        # Анализируем данные
        print("\nПримеры данных MOEX (первые 3):")
        for i, sec in enumerate(moex_data[:3]):
            print(f"\n{i+1}. {sec.get('SHORTNAME', 'N/A')}")
            print(f"   SECID: {sec.get('SECID', 'N/A')}")
            print(f"   ISIN: {sec.get('ISIN', 'N/A')}")
            print(f"   BOARDID: {sec.get('BOARDID', 'N/A')}")
            print(f"   CURRENCYID: {sec.get('CURRENCYID', 'N/A')}")
            print(f"   SECTYPE: {sec.get('SECTYPE', 'N/A')}")
            print(f"   INSTRID: {sec.get('INSTRID', 'N/A')}")
        
        # Группируем по ISIN (чтобы понять, сколько ценных бумаг у одной компании)
        isin_groups = defaultdict(list)
        for sec in moex_data:
            isin = sec.get('ISIN', '')
            if isin:
                isin_groups[isin].append(sec.get('SECID', ''))
        
        # Находим компании с несколькими ценными бумагами
        multiple_securities = {isin: secids for isin, secids in isin_groups.items() if len(secids) > 1}
        print(f"\nКомпаний с несколькими ценными бумагами: {len(multiple_securities)}")
        if multiple_securities:
            print("\nПримеры компаний с несколькими ценными бумагами:")
            for isin, secids in list(multiple_securities.items())[:5]:
                print(f"  ISIN {isin}: {secids}")
        
        return moex_data, columns
        
    except Exception as e:
        print(f"Ошибка при запросе к MOEX API: {e}")
        return [], []


def get_tinkoff_companies():
    """Получает данные из T Invest API"""
    print("\n" + "="*80)
    print("ЗАПРОС К T INVEST API")
    print("="*80)
    
    token = os.getenv('TINKOFF_TOKEN')
    
    if not token or token == 'tocken':
        print("ОШИБКА: TINKOFF_TOKEN не настроен")
        return [], []
    
    token = token.strip()
    base_url = "https://invest-public-api.tinkoff.ru/rest"
    url = f"{base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "instrument_status": "INSTRUMENT_STATUS_BASE"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        print(f"Ключи в ответе T Invest API: {list(data.keys()) if isinstance(data, dict) else 'не словарь'}")
        
        # Извлекаем инструменты
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
        
        if not instruments:
            print("Не удалось найти инструменты в ответе")
            print(f"Структура данных: {type(data)}")
            if isinstance(data, dict):
                print(f"Доступные ключи: {list(data.keys())}")
                # Сохраним полный ответ для анализа
                with open('/tmp/tinkoff_response.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print("Полный ответ сохранен в /tmp/tinkoff_response.json")
            return [], []
        
        print(f"Всего инструментов получено: {len(instruments)}")
        
        # Показываем структуру первого инструмента
        if instruments and len(instruments) > 0:
            print("\nСтруктура первого инструмента:")
            first_instrument = instruments[0]
            if isinstance(first_instrument, dict):
                print(f"Ключи: {list(first_instrument.keys())}")
                print("\nПример данных первого инструмента:")
                for key, value in list(first_instrument.items())[:15]:
                    print(f"  {key}: {value}")
        
        # Фильтруем российские компании
        tinkoff_data = []
        filtered_count = 0
        skipped_count = 0
        
        for instrument in instruments:
            if not isinstance(instrument, dict):
                continue
            
            # Извлекаем данные
            company = {
                'figi': instrument.get('figi') or instrument.get('FIGI') or '',
                'ticker': instrument.get('ticker') or instrument.get('TICKER') or '',
                'name': instrument.get('name') or instrument.get('NAME') or '',
                'isin': instrument.get('isin') or instrument.get('ISIN'),
                'sector': instrument.get('sector') or instrument.get('SECTOR'),
                'currency': instrument.get('currency') or instrument.get('CURRENCY'),
                'lot': instrument.get('lot') or instrument.get('LOT'),
                'country_of_risk': instrument.get('countryOfRisk') or instrument.get('country_of_risk'),
                'exchange': instrument.get('exchange') or instrument.get('EXCHANGE'),
            }
            
            if not (company['figi'] and company['ticker']):
                skipped_count += 1
                continue
            
            # Фильтрация
            is_russian = False
            is_moex = False
            
            if company['isin']:
                is_russian = str(company['isin']).upper().startswith('RU')
            
            if company['country_of_risk']:
                country = str(company['country_of_risk']).upper()
                is_russian = is_russian or 'RU' in country or 'RUS' in country or 'RUSSIA' in country
            
            if company['exchange']:
                exchange = str(company['exchange']).upper()
                is_moex = 'MOEX' in exchange or 'MOSCOW' in exchange or 'MCX' in exchange
            
            if company['currency'] and str(company['currency']).upper() == 'RUB':
                is_russian = True
            
            if is_russian or is_moex:
                tinkoff_data.append(company)
                filtered_count += 1
            else:
                skipped_count += 1
        
        print(f"\nОтфильтровано российских/Мосбиржа: {filtered_count}")
        print(f"Пропущено: {skipped_count}")
        
        # Примеры данных
        print("\nПримеры данных T Invest API (первые 3):")
        for i, comp in enumerate(tinkoff_data[:3]):
            print(f"\n{i+1}. {comp.get('name', 'N/A')}")
            print(f"   TICKER: {comp.get('ticker', 'N/A')}")
            print(f"   FIGI: {comp.get('figi', 'N/A')}")
            print(f"   ISIN: {comp.get('isin', 'N/A')}")
            print(f"   CURRENCY: {comp.get('currency', 'N/A')}")
            print(f"   EXCHANGE: {comp.get('exchange', 'N/A')}")
            print(f"   COUNTRY_OF_RISK: {comp.get('country_of_risk', 'N/A')}")
        
        return tinkoff_data, list(instruments[0].keys()) if instruments and isinstance(instruments[0], dict) else []
        
    except Exception as e:
        print(f"Ошибка при запросе к T Invest API: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Статус: {e.response.status_code}")
            print(f"Ответ: {e.response.text[:500]}")
        return [], []


def compare_apis():
    """Сравнивает данные из обоих API"""
    print("\n" + "="*80)
    print("СРАВНЕНИЕ ДАННЫХ")
    print("="*80)
    
    moex_data, moex_columns = get_moex_securities()
    tinkoff_data, tinkoff_columns = get_tinkoff_companies()
    
    if not moex_data or not tinkoff_data:
        print("\nНе удалось получить данные для сравнения")
        return
    
    print("\n" + "="*80)
    print("АНАЛИЗ РАЗЛИЧИЙ")
    print("="*80)
    
    # 1. Количество записей
    print(f"\n1. КОЛИЧЕСТВО ЗАПИСЕЙ:")
    print(f"   MOEX API: {len(moex_data)} ценных бумаг")
    print(f"   T Invest API: {len(tinkoff_data)} компаний")
    print(f"   Разница: {len(moex_data) - len(tinkoff_data)} позиций")
    
    # 2. Уникальные компании по ISIN
    moex_isins = set()
    for sec in moex_data:
        isin = sec.get('ISIN', '')
        if isin:
            moex_isins.add(isin)
    
    tinkoff_isins = set()
    for comp in tinkoff_data:
        isin = comp.get('isin', '')
        if isin:
            tinkoff_isins.add(isin)
    
    print(f"\n2. УНИКАЛЬНЫЕ КОМПАНИИ (по ISIN):")
    print(f"   MOEX API: {len(moex_isins)} уникальных ISIN")
    print(f"   T Invest API: {len(tinkoff_isins)} уникальных ISIN")
    
    # Компании, которые есть в MOEX, но нет в T Invest
    only_moex = moex_isins - tinkoff_isins
    only_tinkoff = tinkoff_isins - moex_isins
    
    print(f"\n3. КОМПАНИИ ТОЛЬКО В MOEX: {len(only_moex)}")
    if only_moex:
        print("   Примеры (первые 10):")
        for isin in list(only_moex)[:10]:
            # Найдем название компании
            for sec in moex_data:
                if sec.get('ISIN') == isin:
                    print(f"     {isin} - {sec.get('SHORTNAME', 'N/A')}")
                    break
    
    print(f"\n4. КОМПАНИИ ТОЛЬКО В T INVEST: {len(only_tinkoff)}")
    if only_tinkoff:
        print("   Примеры (первые 10):")
        for isin in list(only_tinkoff)[:10]:
            for comp in tinkoff_data:
                if comp.get('isin') == isin:
                    print(f"     {isin} - {comp.get('name', 'N/A')}")
                    break
    
    # 5. Общие компании
    common_isins = moex_isins & tinkoff_isins
    print(f"\n5. ОБЩИЕ КОМПАНИИ: {len(common_isins)}")
    
    # 6. Поля данных
    print(f"\n6. ПОЛЯ ДАННЫХ:")
    print(f"   MOEX API колонки ({len(moex_columns)}): {moex_columns}")
    print(f"   T Invest API ключи ({len(tinkoff_columns)}): {tinkoff_columns}")
    
    # 7. Что есть в MOEX, но нет в T Invest
    moex_fields = set(col.lower() for col in moex_columns)
    tinkoff_fields = set(key.lower() for key in tinkoff_columns)
    
    missing_in_tinkoff = moex_fields - tinkoff_fields
    print(f"\n7. ПОЛЯ, КОТОРЫЕ ЕСТЬ В MOEX, НО НЕТ В T INVEST:")
    if missing_in_tinkoff:
        for field in sorted(missing_in_tinkoff):
            print(f"   - {field}")
    else:
        print("   Нет уникальных полей")
    
    # 8. Что есть в T Invest, но нет в MOEX
    missing_in_moex = tinkoff_fields - moex_fields
    print(f"\n8. ПОЛЯ, КОТОРЫЕ ЕСТЬ В T INVEST, НО НЕТ В MOEX:")
    if missing_in_moex:
        for field in sorted(missing_in_moex):
            print(f"   - {field}")
    else:
        print("   Нет уникальных полей")
    
    # 9. Пример сравнения одной компании
    if common_isins:
        example_isin = list(common_isins)[0]
        print(f"\n9. ПРИМЕР СРАВНЕНИЯ КОМПАНИИ (ISIN: {example_isin}):")
        
        # Данные из MOEX
        moex_examples = [sec for sec in moex_data if sec.get('ISIN') == example_isin]
        print(f"\n   MOEX API - найдено {len(moex_examples)} ценных бумаг:")
        for i, sec in enumerate(moex_examples[:3]):
            print(f"     {i+1}. SECID: {sec.get('SECID')}, BOARDID: {sec.get('BOARDID')}, NAME: {sec.get('SHORTNAME', 'N/A')}")
        
        # Данные из T Invest
        tinkoff_example = next((comp for comp in tinkoff_data if comp.get('isin') == example_isin), None)
        if tinkoff_example:
            print(f"\n   T Invest API - найдена 1 компания:")
            print(f"     TICKER: {tinkoff_example.get('ticker')}, NAME: {tinkoff_example.get('name', 'N/A')}")
    
    print("\n" + "="*80)
    print("АНАЛИЗ ЗАВЕРШЕН")
    print("="*80)


if __name__ == "__main__":
    compare_apis()

