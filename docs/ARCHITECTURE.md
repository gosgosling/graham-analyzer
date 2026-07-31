# Graham Analyzer - Исчерпывающее руководство по архитектуре проекта

## 📋 Содержание

1. [Обзор проекта](#обзор-проекта)
2. [Структура проекта](#структура-проекта)
3. [Точка входа: main.py](#точка-входа-mainpy)
4. [Архитектура приложения](#архитектура-приложения)
5. [Детальное описание компонентов](#детальное-описание-компонентов)
6. [Поток данных](#поток-данных)
7. [Запуск и развертывание](#запуск-и-развертывание)
8. [Взаимодействие компонентов](#взаимодействие-компонентов)

---

## 🎯 Обзор проекта

**Graham Analyzer** - это веб-приложение для анализа российских компаний по принципам Бенджамина Грэма (value investing). Проект состоит из:

- **Backend** (Python/FastAPI) - REST API для получения данных о компаниях и их анализа
- **Frontend** (React/TypeScript) - пользовательский интерфейс
- **База данных** (PostgreSQL) - хранение информации о компаниях

### Основные функции:
1. Получение данных о компаниях из внешних API (Tinkoff Invest, MOEX)
2. Хранение компаний в базе данных
3. Анализ компаний по мультипликаторам (P/E, P/B, ROE и др.)
4. Классификация компаний: недооцененные, стабильные, переоцененные

---

## 📁 Структура проекта

```
graham-analyzer/
├── backend/
│   ├── app/
│   │   ├── main.py              # ⭐ точка входа: роутеры, CORS, старт планировщика
│   │   ├── config.py            # настройки из .env (БД, LLM, TINKOFF_TOKEN, SQL_ECHO)
│   │   ├── database.py          # движок и сессии SQLAlchemy
│   │   ├── scheduler.py         # APScheduler: ежедневное обновление цен
│   │   │
│   │   ├── models/              # таблицы БД — по одной сущности на файл
│   │   ├── schemas/             # Pydantic-схемы API, по сущностям
│   │   │   └── report.py        #   ReportFigures → Create / Response
│   │   │
│   │   ├── routers/             # HTTP-слой: тонкий, вся логика в services
│   │   │   └── pipeline_errors.py  # ошибки LLM-конвейера → коды ответа
│   │   │
│   │   ├── services/            # бизнес-логика, по доменам
│   │   │   ├── analysis/        #   мультипликаторы, LTM, отраслевые профили,
│   │   │   │                    #   вердикт по Грэму — расчётное ядро
│   │   │   ├── report_parser/   #   PDF → LLM → черновик отчёта, сверка с эталоном
│   │   │   ├── reports/         #   CRUD отчётов
│   │   │   ├── companies/       #   компании, синхронизация с T-Invest
│   │   │   ├── market/          #   цены: история MOEX, текущие T-Invest
│   │   │   ├── disclosure/      #   календарь отчётности и очередь парсинга
│   │   │   ├── mass_parse/      #   массовый прогон PDF (очередь на таблицах БД)
│   │   │   ├── dividends/       #   непрерывность выплат по Грэму
│   │   │   ├── bonds/, admin/   #   облигации, бэкапы
│   │   │
│   │   └── utils/               # клиенты внешних API и конвертации
│   │
│   ├── alembic/                 # миграции
│   ├── tests/                   # тесты (БД и сеть не нужны, кроме live-прогона LLM)
│   │   └── fixtures/golden/     #   эталонные отчёты для метрики качества парсинга
│   └── scripts/                 # скрипты, которым нужен venv и импорт app
│
├── frontend/src/
│   ├── pages/                   # экраны-маршруты
│   ├── components/              # переиспользуемые блоки (панель мультипликаторов, формы)
│   ├── services/                # клиенты REST API
│   └── utils/                   # чистые функции: форматирование, FCF, ROE, профили
│
├── tools/
│   └── edisclosure-scraper/     # Playwright-робот e-disclosure.ru: поиск, скачивание
│                                # ZIP, разбор меток периодов. Вызывается приложением
│                                # через app/services/disclosure/edisclosure_client.py
├── scripts/                     # скрипты уровня репозитория (без импорта app):
│                                # бэкап и восстановление БД, метрики качества кода
├── docs/                        # архитектура, планы, отчёты о качестве
└── plans/                       # roadmap и правила работы над проектом
```

**Где что искать.** Расчёт живёт в `services/analysis` — это единственное место,
где считаются деньги, и оно покрыто тестами плотнее всего. Роутеры логики не
содержат: их задача — принять запрос, позвать сервис и перевести исключение в
код ответа.

**Два каталога скриптов — не случайность.** Правило: если скрипт импортирует
`app` и требует venv бэкенда, он лежит в `backend/scripts/` (аудит покрытия
базы, выгрузка эталонов, живой прогон качества извлечения). Если он работает с
репозиторием или инфраструктурой и ничего не знает о приложении — в корневом
`scripts/` (бэкап Postgres, метрики качества кода).

**`disclosure` в двух деревьях — тоже не дубль.** В `app/services/disclosure`
лежит слой приложения: календарь отчётности, очередь парсинга, пути к файлам.
В `tools/edisclosure-scraper` — браузерный робот на Playwright, который умеет
ходить по e-disclosure.ru. Логика не пересекается, но связаны они через
`sys.path` (дефис в имени каталога не даёт сделать из него пакет), поэтому
зависимости робота перечислены в `backend/requirements.txt`: без них падает
скачивание отчётов.

---

## 🚀 Точка входа: main.py

### Что такое main.py?

`main.py` - это **главный файл приложения**, который создает и настраивает FastAPI приложение. Это точка входа, с которой начинается работа всего backend.

### Как это работает?

```python
# 1. Импорты
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import companies, companies_router

# 2. Создание экземпляра приложения
app = FastAPI(title='Graham Analyzer')

# 3. Настройка CORS (для работы с frontend)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Разрешаем запросы с frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Подключение роутеров (эндпоинтов API)
app.include_router(companies.router)          # /securities/*
app.include_router(companies_router.router)   # /companies/*

# 5. Простой эндпоинт для проверки здоровья
@app.get('/health')
def health_check():
    return {'status': 'ok'}
```

### Что происходит при запуске?

1. **Импортируются модули** - Python загружает все необходимые файлы
2. **Создается объект `app`** - это экземпляр FastAPI приложения
3. **Настраивается CORS** - разрешаются запросы с frontend
4. **Подключаются роутеры** - регистрируются все API эндпоинты
5. **Приложение готово** - можно принимать HTTP запросы

### Как запускается?

```bash
# Команда запуска
uvicorn app.main:app --reload

# Разбор команды:
# - uvicorn - ASGI сервер (запускает FastAPI)
# - app.main - путь к модулю (app/main.py)
# - app - имя переменной с FastAPI приложением
# - --reload - автоматическая перезагрузка при изменении кода
```

**Важно:** `app.main:app` означает:
- `app` - пакет (директория `app/`)
- `main` - модуль (файл `main.py`)
- `app` - переменная (объект `FastAPI`)

---

## 🏗️ Архитектура приложения

Проект следует архитектуре **MVC (Model-View-Controller)** с элементами **Layered Architecture**:

```
┌─────────────────────────────────────────────────────────┐
│                    HTTP Request                          │
│              (GET /companies, POST /sync)               │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  ROUTERS (routers/)                                      │
│  - Принимают HTTP запросы                                │
│  - Валидируют входные данные (schemas)                  │
│  - Вызывают сервисы                                      │
│  - Возвращают HTTP ответы                                │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  SERVICES (services/)                                    │
│  - Бизнес-логика                                         │
│  - Обработка данных                                      │
│  - Вызовы внешних API (utils/)                           │
│  - Работа с БД через модели                             │
└────────────────────┬────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌──────────────────┐    ┌──────────────────┐
│  MODELS          │    │  UTILS           │
│  (models/)       │    │  (utils/)        │
│  - SQLAlchemy    │    │  - API клиенты   │
│  - Структура БД  │    │  - Вспомогат.    │
└──────────────────┘    └──────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  DATABASE (PostgreSQL)                                   │
│  - Хранение данных                                       │
└─────────────────────────────────────────────────────────┘
```

---

## 📚 Детальное описание компонентов

### 1. config.py - Конфигурация приложения

**Назначение:** Хранение всех настроек приложения (БД, API ключи, и т.д.)

**Как работает:**
```python
# Загружает переменные из .env файла
load_dotenv(dotenv_path=ENV_FILE)

class Settings(BaseSettings):
    # Настройки базы данных
    POSTGRES_USER: str = "graham_user"
    POSTGRES_PASSWORD: str = "12345678"
    POSTGRES_DB: str = "graham_analyzer"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    
    # API ключи
    TINKOFF_TOKEN: str = "your_token_here"
    
    # Метод для формирования URL БД
    @property
    def database_url(self) -> str:
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

# Создается один экземпляр настроек (singleton)
settings = Settings()
```

**Использование:**
- Импортируется в других модулях: `from app.config import settings`
- Используется для подключения к БД, API ключей и т.д.

---

### 2. database.py - Подключение к базе данных

**Назначение:** Настройка SQLAlchemy для работы с PostgreSQL

**Как работает:**
```python
# 1. Создание движка (engine) - подключение к БД
engine = create_engine(
    settings.database_url,  # URL из config.py
    echo=True  # Показывает SQL запросы в консоли (для отладки)
)

# 2. Создание фабрики сессий
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# 3. Базовый класс для моделей
Base = declarative_base()

# 4. Функция-генератор для получения сессии БД
def get_db():
    db = SessionLocal()
    try:
        yield db  # Возвращает сессию
    finally:
        db.close()  # Закрывает сессию после использования
```

**Что такое сессия?**
- Сессия - это "окно" в базу данных
- Через сессию выполняются все операции (SELECT, INSERT, UPDATE, DELETE)
- После использования сессию нужно закрыть

**Использование в FastAPI:**
```python
# В роутере
@router.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    # FastAPI автоматически вызывает get_db()
    # и передает сессию в функцию
    companies = db.query(Company).all()
    return companies
```

---

### 3. models/company.py - Модель данных

**Назначение:** Описание структуры таблицы `companies` в БД

**Как работает:**
```python
class Company(Base):  # Наследуется от Base (из database.py)
    __tablename__ = "companies"  # Имя таблицы в БД
    
    # Поля таблицы
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    figi: Mapped[str] = mapped_column(String, unique=True)
    ticker: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    isin: Mapped[Optional[str]] = mapped_column(String)
    # ... и т.д.
```

**Что делает SQLAlchemy:**
- Преобразует Python класс в SQL таблицу
- Автоматически генерирует SQL запросы
- Обеспечивает типизацию данных

**Создание таблицы:**
Таблицы создаются через **миграции Alembic** (не вручную):
```bash
alembic revision --autogenerate -m "create companies table"
alembic upgrade head
```

---

### 4. schemas.py - Валидация данных

**Назначение:** Pydantic схемы для валидации входных/выходных данных API

**Как работает:**
```python
# Схема для создания компании (входные данные)
class CompanyCreate(BaseModel):
    figi: str
    ticker: str
    name: str
    isin: str
    sector: Optional[str] = None
    # ...

# Схема для ответа API (выходные данные)
class Company(BaseModel):
    figi: str
    ticker: str
    name: str
    # ...
```

**Зачем нужны схемы?**
1. **Валидация** - проверка, что данные корректны
2. **Документация** - автоматическая генерация Swagger/OpenAPI
3. **Типизация** - подсказки в IDE

**Использование:**
```python
@router.post("/companies")
def create_company(company_data: CompanyCreate):  # Автоматическая валидация
    # company_data уже проверен и имеет правильные типы
    ...
```

---

### 5. routers/ - API эндпоинты

**Назначение:** Обработка HTTP запросов

#### companies_router.py - Роутер для компаний (Tinkoff)

```python
router = APIRouter(prefix="/companies", tags=["companies"])

@router.get("/", response_model=list[Company])
def get_companies(skip: int = 0, limit: int = 200, db: Session = Depends(get_db)):
    """
    GET /companies/
    Получает список компаний из БД
    """
    companies = get_all_companies(db, skip=skip, limit=limit)
    return companies

@router.post("/sync")
def sync_companies(db: Session = Depends(get_db)):
    """
    POST /companies/sync
    Синхронизирует компании из Tinkoff API в БД
    """
    stats = sync_companies_from_tinkoff(db)
    return {"status": "success", "statistics": stats}
```

**Что происходит:**
1. Клиент отправляет HTTP запрос: `GET http://localhost:8000/companies/`
2. FastAPI находит соответствующий роутер
3. Вызывается функция `get_companies()`
4. Функция получает сессию БД через `Depends(get_db)`
5. Вызывается сервис `get_all_companies()`
6. Возвращается JSON ответ

#### companies.py - Роутер для ценных бумаг (MOEX)

```python
router = APIRouter(prefix="/securities", tags=["securities"])

@router.get("/", response_model=list[Security])
def get_securities():
    """
    GET /securities/
    Получает список ценных бумаг с MOEX
    """
    securities = get_moex_securities()  # Вызов утилиты
    return securities

@router.get('/analysis', response_model=AnalysisResponse)
def get_analysis_companies():
    """
    GET /securities/analysis
    Анализирует все компании и классифицирует их
    """
    # Получает ценные бумаги
    securities = get_securities()
    
    # Для каждой компании:
    for security in securities:
        multipliers = _get_multipliers_by_company_id(security['id'])
        category = classify_company(multipliers)  # Анализ
        
        # Классификация по категориям
        if category['classify'] == "undervalued":
            undervalued_companies.append(...)
        # ...
    
    return {
        "undervalued": undervalued_companies,
        "stable": stable_companies,
        "overvalued": overvalued_companies
    }
```

---

### 6. services/ - Бизнес-логика

#### company_service.py - CRUD операции с компаниями

**Назначение:** Все операции с компаниями в БД (создание, чтение, обновление)

**Основные функции:**

```python
# 1. Получение компании по ISIN
def get_company_by_isin(db: Session, isin: str) -> Optional[Company]:
    return db.query(Company).filter(Company.isin == isin).first()

# 2. Создание компании
def create_company(db: Session, company_data: CompanyCreate) -> Company:
    db_company = Company(
        figi=company_data.figi,
        ticker=company_data.ticker,
        # ...
    )
    db.add(db_company)      # Добавляет в сессию
    db.commit()             # Сохраняет в БД
    db.refresh(db_company)  # Обновляет объект из БД
    return db_company

# 3. Обновление компании
def update_company(db: Session, isin: str, company_data: CompanyCreate):
    db_company = get_company_by_isin(db, isin)
    if not db_company:
        return None
    
    db_company.ticker = company_data.ticker  # Обновление полей
    # ...
    db.commit()  # Сохранение изменений
    return db_company

# 4. Синхронизация (создать или обновить)
def sync_company(db: Session, company_data: CompanyCreate) -> Company:
    existing = get_company_by_isin(db, company_data.isin)
    if existing:
        return update_company(db, company_data.isin, company_data)
    else:
        return create_company(db, company_data)
```

**Важно:**
- `db.add()` - добавляет объект в сессию (но еще не в БД!)
- `db.commit()` - сохраняет изменения в БД
- `db.refresh()` - обновляет объект данными из БД (получает ID, timestamps и т.д.)

#### graham_analyser.py - Анализ по принципам Грэма

**Назначение:** Классификация компаний на основе финансовых мультипликаторов

**Как работает:**

```python
def classify_company(multipliers):
    """
    Анализирует мультипликаторы и классифицирует компанию:
    - undervalued (недооцененная)
    - stable (стабильная)
    - overvalued (переоцененная)
    """
    pe = multipliers['pe_ratio']           # P/E (цена/прибыль)
    pb = multipliers['pb_ratio']           # P/B (цена/балансовая стоимость)
    debt_to_equity = multipliers['debt_to_equity']  # Долг/капитал
    current_ratio = multipliers['current_ratio']    # Текущая ликвидность
    roe = multipliers['roe']               # ROE (рентабельность капитала)
    dividend_yield = multipliers['dividend_yield'] # Дивидендная доходность
    
    # Оценка каждого показателя
    pe_ratio_status = _evaluate_status(pe, 15, 25, is_higher_better=False)
    pb_ratio_status = _evaluate_status(pb, 1.5, 3.0, is_higher_better=False)
    # ...
    
    # Классификация
    is_undervalued = (
        pe < 15 and 
        pb < 1.5 and 
        debt_to_equity <= 0.5 and 
        current_ratio > 2.0 and 
        roe > 15 and 
        dividend_yield > 3
    )
    
    if is_undervalued:
        classify = "undervalued"
    elif is_stable:
        classify = "stable"
    else:
        classify = "overvalued"
    
    return {
        "classify": classify,
        "pe_ratio_status": pe_ratio_status,
        # ...
    }
```

**Критерии Грэма:**
- **P/E < 15** - компания недорогая
- **P/B < 1.5** - цена ниже балансовой стоимости
- **Долг/Капитал ≤ 0.5** - низкая задолженность
- **Текущая ликвидность > 2.0** - хорошая ликвидность
- **ROE > 15%** - высокая рентабельность
- **Дивиденды > 3%** - хорошие дивиденды

#### sync_service.py - Синхронизация данных

**Назначение:** Загрузка компаний из Tinkoff API в БД

**Как работает:**

```python
def sync_companies_from_tinkoff(db: Session) -> Dict[str, int]:
    """
    1. Получает компании из Tinkoff API
    2. Для каждой компании:
       - Проверяет, существует ли в БД
       - Создает новую или обновляет существующую
    3. Возвращает статистику
    """
    # 1. Получение данных из API
    tinkoff_companies = get_tinkoff_companies()
    
    stats = {
        'total': len(tinkoff_companies),
        'created': 0,
        'updated': 0,
        'errors': 0
    }
    
    # 2. Обработка каждой компании
    for company_dict in tinkoff_companies:
        try:
            # Преобразование в схему
            company_data = CompanyCreate(
                figi=company_dict['figi'],
                ticker=company_dict['ticker'],
                # ...
            )
            
            # Синхронизация (создать или обновить)
            sync_company(db, company_data)
            
            # Обновление статистики
            if was_existing:
                stats['updated'] += 1
            else:
                stats['created'] += 1
        except Exception as e:
            stats['errors'] += 1
    
    return stats
```

---

### 7. utils/ - Вспомогательные утилиты

#### tinkoff_client.py - Клиент Tinkoff Invest API

**Назначение:** Получение данных о компаниях из Tinkoff Invest API

**Как работает:**

```python
def get_tinkoff_companies() -> List[Dict]:
    """
    1. Получает токен из переменных окружения
    2. Отправляет POST запрос к Tinkoff API
    3. Фильтрует только российские компании
    4. Возвращает список компаний
    """
    token = os.getenv('TINKOFF_TOKEN')
    
    # URL API
    url = "https://invest-public-api.tinkoff.ru/rest/tinkoff.public.invest.api.contract.v1.InstrumentsService/Shares"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "instrument_status": "INSTRUMENT_STATUS_BASE"
    }
    
    # Отправка запроса
    response = requests.post(url, json=payload, headers=headers)
    data = response.json()
    
    # Обработка ответа
    instruments = data.get('instruments', [])
    
    # Фильтрация: только российские компании
    companies = []
    for instrument in instruments:
        is_russian = (
            instrument.get('isin', '').startswith('RU') or
            instrument.get('countryOfRisk') == 'RU' or
            instrument.get('currency') == 'RUB'
        )
        
        if is_russian:
            companies.append({
                'figi': instrument.get('figi'),
                'ticker': instrument.get('ticker'),
                'name': instrument.get('name'),
                # ...
            })
    
    return companies
```

#### moex_client.py - Клиент MOEX API

**Назначение:** Получение данных о ценных бумагах с Московской биржи

**Как работает:**

```python
def get_moex_securities() -> List[Dict]:
    """
    1. Отправляет GET запрос к MOEX API
    2. Получает список всех ценных бумаг
    3. Фильтрует только акции (INSTRID='EQIN')
    4. Нормализует ключи (UPPERCASE -> lowercase)
    5. Возвращает список
    """
    url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json"
    
    response = requests.get(url)
    data = response.json()
    
    # Извлечение данных
    securities = data.get('securities', {})
    columns = securities.get('columns', [])
    rows = securities.get('data', [])
    
    # Фильтрация и нормализация
    companies = []
    for row in rows:
        # Фильтр: только акции
        if row[instrid_idx] == 'EQIN':
            company = dict(zip(columns, row))
            # Нормализация ключей
            normalized = {k.lower(): v for k, v in company.items()}
            companies.append(normalized)
    
    return companies
```

---

## 🔄 Поток данных

### Пример 1: Получение списка компаний

```
1. Клиент (Frontend/Browser)
   ↓
   GET http://localhost:8000/companies/
   
2. FastAPI (main.py)
   ↓
   Находит роутер: companies_router.py
   
3. Роутер (companies_router.py)
   ↓
   @router.get("/")
   def get_companies(db: Session = Depends(get_db))
   
4. Dependency Injection (database.py)
   ↓
   get_db() создает сессию БД
   
5. Сервис (company_service.py)
   ↓
   get_all_companies(db)
   
6. SQLAlchemy (models/company.py)
   ↓
   db.query(Company).all()
   → SQL: SELECT * FROM companies
   
7. База данных (PostgreSQL)
   ↓
   Возвращает данные
   
8. Обратный путь
   ↓
   Company объекты → Pydantic схемы → JSON → HTTP Response
   
9. Клиент получает JSON
   [
     {
       "figi": "BBG004730N88",
       "ticker": "SBER",
       "name": "Сбербанк",
       ...
     },
     ...
   ]
```

### Пример 2: Синхронизация компаний

```
1. Клиент
   ↓
   POST http://localhost:8000/companies/sync
   
2. Роутер (companies_router.py)
   ↓
   @router.post("/sync")
   def sync_companies(db: Session = Depends(get_db))
   
3. Сервис (sync_service.py)
   ↓
   sync_companies_from_tinkoff(db)
   
4. Утилита (tinkoff_client.py)
   ↓
   get_tinkoff_companies()
   → HTTP запрос к Tinkoff API
   → Получение списка компаний
   
5. Обработка каждой компании
   ↓
   Для каждой компании:
     - CompanyCreate схема
     - sync_company(db, company_data)
   
6. Сервис (company_service.py)
   ↓
   sync_company() проверяет существование
   → create_company() или update_company()
   
7. SQLAlchemy
   ↓
   db.add() → db.commit()
   → SQL: INSERT или UPDATE
   
8. База данных
   ↓
   Сохранение данных
   
9. Возврат статистики
   ↓
   {
     "status": "success",
     "statistics": {
       "total": 150,
       "created": 120,
       "updated": 30,
       "errors": 0
     }
   }
```

### Пример 3: Анализ компаний

```
1. Клиент
   ↓
   GET http://localhost:8000/securities/analysis
   
2. Роутер (companies.py)
   ↓
   @router.get('/analysis')
   def get_analysis_companies()
   
3. Утилита (moex_client.py)
   ↓
   get_moex_securities()
   → Получение ценных бумаг с MOEX
   
4. Для каждой ценной бумаги:
   ↓
   a) Получение мультипликаторов (mock_data.py)
   b) Анализ (graham_analyser.py)
      ↓
      classify_company(multipliers)
      → Оценка P/E, P/B, ROE и др.
      → Классификация: undervalued/stable/overvalued
   
5. Группировка результатов
   ↓
   {
     "undervalued": [...],
     "stable": [...],
     "overvalued": [...]
   }
   
6. Возврат клиенту
```

---

## 🚀 Запуск и развертывание

### 1. Подготовка окружения

```bash
# 1. Создание виртуального окружения
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# 2. Установка зависимостей
pip install -r requirements.txt

# 3. Настройка переменных окружения
# Создать файл .env в корне проекта:
TINKOFF_TOKEN=your_actual_token_here
POSTGRES_USER=graham_user
POSTGRES_PASSWORD=12345678
POSTGRES_DB=graham_analyzer
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### 2. Настройка базы данных

```bash
# 1. Создание БД (если еще не создана)
createdb graham_analyzer

# 2. Применение миграций
cd backend
alembic upgrade head
```

### 3. Запуск backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload

# Приложение доступно на:
# - API: http://127.0.0.1:8000
# - Документация: http://127.0.0.1:8000/docs
# - Альтернативная документация: http://127.0.0.1:8000/redoc
```

### 4. Запуск frontend

```bash
cd frontend
npm install  # Первый раз
npm start

# Приложение доступно на:
# http://localhost:3000
```

### 5. Проверка работы

```bash
# Проверка здоровья API
curl http://localhost:8000/health
# Ответ: {"status":"ok"}

# Получение компаний
curl http://localhost:8000/companies/

# Синхронизация компаний
curl -X POST http://localhost:8000/companies/sync
```

---

## 🔗 Взаимодействие компонентов

### Зависимости между модулями

```
main.py
  ├── routers/companies_router.py
  │     ├── services/company_service.py
  │     │     ├── models/company.py
  │     │     └── database.py
  │     └── services/sync_service.py
  │           ├── utils/tinkoff_client.py
  │           │     └── config.py
  │           └── services/company_service.py
  │
  └── routers/companies.py
        ├── utils/moex_client.py
        ├── services/graham_analyser.py
        └── data/mock_data.py
```

### Порядок инициализации при запуске

1. **Импорт config.py**
   - Загружает переменные окружения
   - Создает объект `settings`

2. **Импорт database.py**
   - Использует `settings.database_url`
   - Создает `engine` и `SessionLocal`

3. **Импорт models/**
   - Модели наследуются от `Base` (из database.py)
   - Определяют структуру таблиц

4. **Импорт utils/**
   - Клиенты для внешних API
   - Используют `config.settings` для токенов

5. **Импорт services/**
   - Используют модели и утилиты
   - Содержат бизнес-логику

6. **Импорт routers/**
   - Используют сервисы
   - Определяют API эндпоинты

7. **Импорт main.py**
   - Создает FastAPI приложение
   - Подключает роутеры
   - Настраивает CORS

8. **Запуск uvicorn**
   - Загружает приложение
   - Запускает HTTP сервер
   - Готов принимать запросы

---

## 📝 Ключевые концепции

### 1. Dependency Injection (DI)

FastAPI использует DI для автоматической передачи зависимостей:

```python
def get_companies(db: Session = Depends(get_db)):
    # FastAPI автоматически:
    # 1. Вызывает get_db()
    # 2. Получает сессию БД
    # 3. Передает в функцию
    # 4. Закрывает сессию после выполнения
```

### 2. ORM (Object-Relational Mapping)

SQLAlchemy - это ORM, который:
- Преобразует Python классы в SQL таблицы
- Преобразует Python объекты в SQL строки
- Автоматически генерирует SQL запросы

```python
# Вместо SQL:
# SELECT * FROM companies WHERE isin = 'RU0009029540'

# Пишем на Python:
company = db.query(Company).filter(Company.isin == 'RU0009029540').first()
```

### 3. Миграции (Alembic)

Миграции - это версионирование схемы БД:

```bash
# Создание миграции
alembic revision --autogenerate -m "add new field"

# Применение миграции
alembic upgrade head

# Откат миграции
alembic downgrade -1
```

### 4. CORS (Cross-Origin Resource Sharing)

CORS позволяет frontend (localhost:3000) делать запросы к backend (localhost:8000):

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Разрешенный источник
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 🎓 Резюме для начинающего разработчика

### Что нужно понимать:

1. **main.py** - точка входа, создает и настраивает приложение
2. **routers/** - обрабатывают HTTP запросы (API эндпоинты)
3. **services/** - содержат бизнес-логику (что делать с данными)
4. **models/** - описывают структуру таблиц БД
5. **utils/** - вспомогательные функции (API клиенты и т.д.)
6. **config.py** - все настройки приложения
7. **database.py** - подключение к БД

### Поток работы:

1. **HTTP запрос** → роутер
2. **Роутер** → вызывает сервис
3. **Сервис** → работает с БД через модели или вызывает утилиты
4. **Результат** → возвращается через роутер как JSON

### Важные моменты:

- Все компоненты связаны через импорты
- FastAPI автоматически обрабатывает HTTP запросы
- SQLAlchemy автоматически генерирует SQL
- Pydantic автоматически валидирует данные
- Dependency Injection автоматически передает зависимости

---

## 📚 Дополнительные ресурсы

- [FastAPI документация](https://fastapi.tiangolo.com/)
- [SQLAlchemy документация](https://docs.sqlalchemy.org/)
- [Pydantic документация](https://docs.pydantic.dev/)
- [Alembic документация](https://alembic.sqlalchemy.org/)

---

**Автор:** ИИ-агент  
**Дата:** 2025  
**Версия:** 1.0
