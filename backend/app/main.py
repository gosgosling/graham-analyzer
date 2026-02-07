from unicodedata import category
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Optional
#import debugpy
from app.routers import companies_router, companies, reports_router
from app.schemas import AnalysisResponse, Security, Multipliers



app = FastAPI(title='Graham Analyzer')

# Настройка CORS для работы с frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # URL вашего React приложения
    allow_credentials=True,
    allow_methods=["*"],  # Разрешить все HTTP методы
    allow_headers=["*"],  # Разрешить все заголовки
)

app.include_router(companies.router)  # Роутер для ценных бумаг (MOEX)
app.include_router(companies_router.router)  # Роутер для компаний (Tinkoff)
app.include_router(reports_router.router)



@app.get('/health')
def health_check():
    return {'status': 'ok'}






#if __name__ == "__main__":
 #   debugpy.listen(("0.0.0.0", 5678))
   # print("Waiting for debugger attach...")
  #  debugpy.wait_for_client()
    

 #   uvicorn.run(app, host="0.0.0.0", port=8000)
