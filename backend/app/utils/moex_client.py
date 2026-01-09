import requests
from typing import List, Dict

def get_moex_securities() -> List[Dict]:
    """
    Получает список акций компаний, торгующих на Мосбирже.
    Фильтрует только акции (INSTRID='EQIN', SECTYPE='1').
    В будущем в БД будет таблица со всеми ценными бумагами для расширения.
    
    Returns:
        Список словарей с информацией об акциях компаний
    """
    url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json"
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # Проверка на ошибки HTTP
        
        data = response.json()
        
        # Извлекаем данные из ответа
        securities = data.get('securities', {})
        columns = securities.get('columns', [])
        rows = securities.get('data', [])
        
        # Определяем индексы нужных колонок для фильтрации
        instrid_idx = columns.index('INSTRID') if 'INSTRID' in columns else None
        sectype_idx = columns.index('SECTYPE') if 'SECTYPE' in columns else None
        
        # Преобразуем в список словарей и нормализуем ключи (MOEX использует UPPERCASE)
        # Фильтруем только акции: INSTRID='EQIN' или SECTYPE='1'
        companies = []
        for row in rows:
            # Фильтрация: только акции
            is_stock = False
            if instrid_idx is not None and row[instrid_idx] == 'EQIN':
                is_stock = True
            elif sectype_idx is not None and row[sectype_idx] == '1':
                is_stock = True
            
            if not is_stock:
                continue  # Пропускаем не-акции
            
            company = dict(zip(columns, row))
            # Нормализуем ключи: приводим к lowercase для соответствия схеме
            normalized_company = {}
            for key, value in company.items():
                # Приводим ключ к lowercase
                normalized_key = key.lower()
                normalized_company[normalized_key] = value
            companies.append(normalized_company)
        
        return companies
        
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при запросе к MOEX API: {e}")
        return []