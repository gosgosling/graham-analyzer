from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(
    settings.database_url,
    # Лог каждого SQL-запроса. По умолчанию выключен: на публичном демо он
    # засоряет вывод и утаскивает в логи содержимое отчётов. Включается через
    # SQL_ECHO=true в .env, когда нужно отладить конкретный запрос.
    echo=settings.SQL_ECHO,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Функция для получения сессии БД (dependency для FastAPI)
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
