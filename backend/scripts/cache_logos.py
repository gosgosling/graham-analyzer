"""Скачать логотипы всех компаний в локальный кэш.

    ./venv/bin/python -m scripts.cache_logos

Повторный запуск безопасен: уже скачанные пропускаются. На сервере
запускать после первого развёртывания (или ждать — кэш заполняется и сам,
при первом показе каждой страницы).
"""
from app.database import SessionLocal
from app.models.company import Company
from app.services.companies import logo_cache


def main() -> int:
    db = SessionLocal()
    try:
        result = logo_cache.cache_all(db.query(Company).order_by(Company.ticker).all())
    finally:
        db.close()
    print(f"Логотипов в кэше: {result['cached']}, не найдено: {len(result['missing'])}")
    if result["missing"]:
        print("Без логотипа:", ", ".join(result["missing"]))
    print("Каталог:", logo_cache.status()["dir"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
