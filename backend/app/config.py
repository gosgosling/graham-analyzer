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

    # ─── LLM для AI-парсера финансовых отчётов ───
    # Один OpenAI-совместимый API работает с OpenAI / Ollama / OpenRouter.
    LLM_PROVIDER: str = "openai"  # openai | ollama | openrouter
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_TEMPERATURE: float = 0.0
    LLM_REQUEST_TIMEOUT: int = 600

    @property
    def llm_configured(self) -> bool:
        """LLM настроен? Для Ollama api_key может быть пустым, base_url указан."""
        if self.LLM_PROVIDER.lower() == "ollama":
            return bool(self.LLM_BASE_URL and self.LLM_MODEL)
        return bool(self.LLM_API_KEY and self.LLM_MODEL)

    @property
    def extraction_model_label(self) -> str:
        """Идентификатор модели для колонки `financial_reports.extraction_model`."""
        return f"{self.LLM_PROVIDER}:{self.LLM_MODEL}"

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