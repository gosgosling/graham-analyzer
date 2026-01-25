from sqlalchemy.orm import Session
from typing import List, Dict
from app.utils.tinkoff_client import get_tinkoff_companies
from app.schemas import CompanyCreate
from app.services.company_service import sync_company
from app.models.company import Company

def sync_companies_from_tinkoff(db: Session) -> Dict[str, int]:
    """
    Синхронизирует компании из Tinkoff API в базу данных.
    
    Процесс:
    1. Получает список компаний из Tinkoff API
    2. Преобразует данные в формат CompanyCreate
    3. Для каждой компании вызывает sync_company (создает или обновляет)
    
    Args:
        db: Сессия базы данных
        
    Returns:
        Словарь со статистикой:
        {
            'total': общее количество компаний из API,
            'created': количество созданных,
            'updated': количество обновленных,
            'errors': количество ошибок
        }
    """

    tinkoff_companies = get_tinkoff_companies()

    if not tinkoff_companies:
        return {
            'total': 0,
            'created': 0,
            'updated': 0,
            'errors': 0
        }
    
    stats ={
        'total': len(tinkoff_companies),
        'created': 0,
        'updated': 0,
        'errors': 0
    }

    existing_isins = {
        company.isin for company in db.query(Company).all()
    }

    for company_dict in tinkoff_companies:
        try:
            company_data = CompanyCreate(
                figi=company_dict['figi'],
                ticker=company_dict['ticker'],
                name=company_dict['name'],
                isin=company_dict.get('isin', ''),
                sector=company_dict.get('sector'),
                currency=company_dict.get('currency', 'RUB'),
                lot=company_dict.get('lot', 1),
                api_trade_available_flag=company_dict.get('api_trade_available_flag', False)
            )

            # Проверяем, существует ли компания
            was_existing = company_data.isin in existing_isins

            sync_company(db, company_data)

            if was_existing:
                stats['updated'] += 1
            else:
                stats['created'] += 1
                existing_isins.add(company_data.isin)

        except Exception as e:
            print(f'Ошибка при синхронизации компании: {company_dict.get('figi', 'unknown')}: {e}')
            stats['errors'] += 1

    return stats