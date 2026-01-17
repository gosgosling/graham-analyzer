from pydantic_settings import BaseSettings
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / '.env'
load_dotenv(dotenv_path=ENV_FILE)

class Settings(BaseSettings):
    # Application
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"
    
    # Database
    POSTGRES_USER: str = "graham_user"
    POSTGRES_PASSWORD: str = "12345678"
    POSTGRES_DB: str = "graham_analyzer"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[str] = None  # Опционально, если указан напрямую в .env
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Tinkoff Invest API
    TINKOFF_TOKEN: str = "your_token_here"
    
    @property
    def database_url(self) -> str:
        """Возвращает DATABASE_URL из .env или формирует из компонентов"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    
    class Config:
        env_file = ENV_FILE
        case_sensitive = True

settings = Settings()