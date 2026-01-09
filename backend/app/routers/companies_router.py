from fastapi import APIRouter, HTTPException
from app.schemas import Company
from app.utils.tinkoff_client import get_tinkoff_companies

router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("/", response_model=list[Company])
def get_companies():
    """
    Получает список компаний из Tinkoff Invest API.
    Требуется настройка TINKOFF_TOKEN в .env файле.
    """
    try:
        companies = get_tinkoff_companies()
        
        if not companies:
            # Логируем для диагностики
            print("Предупреждение: get_tinkoff_companies вернул пустой список")
            print("Возможные причины:")
            print("1. TINKOFF_TOKEN не настроен в .env файле")
            print("2. Токен невалидный или истек")
            print("3. Проблема с подключением к T Invest API")
            return []
        
        return companies
    except Exception as e:
        print(f"Ошибка в get_companies: {e}")
        # Возвращаем пустой список вместо исключения, чтобы фронтенд мог обработать
        return []

