"""Конфигурация CLI-утилиты AI-парсера.

Основные настройки парсинга (LLM, БД) живут в корневом пакете backend.
Здесь только специфичные для CLI параметры: путь к папке с отчётами.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent

# Загружаем локальный .env (может переопределить настройки LLM)
load_dotenv(BASE_DIR / ".env")
# Потом — корневой .env (без override, т.е. локальный .env имеет приоритет)
load_dotenv(PROJECT_ROOT / ".env", override=False)

# Подключаем backend к sys.path, чтобы импортировать app.*
_BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


@dataclass(frozen=True)
class CliSettings:
    reports_dir: Path


cli_settings = CliSettings(
    reports_dir=Path(os.getenv("REPORTS_DIR", "/home/devops/Reports")),
)
