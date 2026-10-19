"""Кэш расчётов по версии данных.

Скринер, сравнение, обзор рынка и оценка считаются из одних и тех же отчётов
и цен, а меняются они редко: цены — раз в день, отчёты — когда их загружают.
Пересчитывать всё на каждый запрос незачем — скринер, например, делает около
семисот запросов к базе и отвечает почти две секунды.

Результат хранится в памяти процесса вместе с версией данных, по которой он
посчитан. Версия меняется от любой записи в таблицы с данными — и только
тогда результат считается заново. Времени жизни у записей нет: пока данные
не менялись, ответ тот же самый.

Версия складывается из трёх частей:

1. **Свои записи процесса.** После коммита сессии, в которой что-то писалось
   в таблицы с данными, счётчик увеличивается сразу. Загрузил отчёт — следующий
   же запрос видит новые цифры.
2. **Записи других процессов** (второй воркер, скрипт из консоли). Их видно
   по счётчикам строк в `pg_stat_user_tables`. Postgres обновляет их с
   задержкой до десяти секунд — дольше этого чужая правка не устаревает.
3. **Дата.** Часть расчётов зависит от сегодняшнего дня: средняя ставка ОФЗ
   за месяц, «12 мес.». С новым днём всё считается заново.

Таблицы входа и фоновых заданий в версию не входят: вход пользователя или
прогресс разбора отчётов на цифры не влияют, а сбрасывали бы кэш постоянно.

**Цены — отдельная часть версии.** Текущие цены обновляются каждые пять
минут торгового дня, а полный пересчёт тяжёлых ответов идёт около полутора
минут. Если бы каждая смена цен сбрасывала кэш, сервер пересчитывал бы всё
без остановки, а посетитель ждал бы на каждом запросе. Поэтому версия из двух
частей: **данные** (отчёты, компании, кэш мультипликаторов) и **цены**
(`stock_prices` и ценовые поля `companies`). Сменились данные — ответ
считается заново сразу, как и прежде: загрузил отчёт — видишь новые цифры.
Сменились только цены — отдаётся прежний ответ, пока ему не больше
`PRICE_STALE_SECONDS`, а фоновый прогрев (`cache_warmup`) тем временем
пересчитывает главные страницы под новые цены.

Правка ценовых полей компании другим процессом (скриптом из консоли) видна
по `pg_stat` только как «сменились цены», потому что Postgres не различает
столбцы. Такая правка дойдёт до ответа с той же задержкой, что и цена, —
не дольше нескольких минут.
"""
from __future__ import annotations

import functools
import inspect
import logging
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date
from typing import Any, Callable, Hashable

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.database import engine

logger = logging.getLogger(__name__)

IGNORED_TABLES = frozenset({
    "users", "user_sessions", "auth_tokens",
    "mass_parse_jobs", "mass_parse_items",
    "disclosure_parse_jobs", "disclosure_parse_items", "disclosure_sync_runs",
})

# Таблицы и столбцы цен: их правка меняет ценовую часть версии, а не данные.
PRICE_TABLES = frozenset({"stock_prices", "companies"})
PRICE_COLUMNS = frozenset({"current_price", "price_updated_at", "price_source", "price_quoted_at"})

# Сколько можно отдавать ответ, посчитанный по прежним ценам. Прогрев обычно
# успевает раньше; предел нужен для редких страниц, которые он не греет.
PRICE_STALE_SECONDS = 600.0

# Как часто спрашивать у Postgres чужие записи. Запрос дешёвый (~5 мс), но
# на каждый ответ из кэша его делать незачем.
DB_CHECK_SECONDS = 2.0
MAX_ENTRIES = 2000

_lock = threading.Lock()
_local_version = 0
_local_prices = 0
_db_version: int | None = None
_db_prices: int | None = None
_db_checked_at = 0.0

# ключ → (версия данных, версия цен, когда посчитано, значение)
_store: "OrderedDict[Hashable, tuple[tuple, tuple, float, Any]]" = OrderedDict()
_key_locks: dict[Hashable, threading.Lock] = {}

_FLAG = "ga_data_changed"
_PRICE_FLAG = "ga_prices_changed"
_MISS = object()

# Прогрев пересчитывает записи под новые цены, а не берёт их из кэша.
_strict = threading.local()


def bump() -> None:
    """Данные изменились — все результаты устарели."""
    global _local_version
    with _lock:
        _local_version += 1


def bump_prices() -> None:
    """Сменились только цены — результаты можно отдавать, пока их не пересчитали."""
    global _local_prices
    with _lock:
        _local_prices += 1


def _read_db_counters() -> tuple[int | None, int | None]:
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "select "
                    "coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del) "
                    "  filter (where not (relname = any(:prices))), 0), "
                    "coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del) "
                    "  filter (where relname = any(:prices)), 0) "
                    "from pg_stat_user_tables where not (relname = any(:ignored))"
                ),
                {"ignored": list(IGNORED_TABLES), "prices": list(PRICE_TABLES)},
            ).one()
            return int(row[0] or 0), int(row[1] or 0)
    except Exception as e:  # статистика — подстраховка, без неё кэш тоже работает
        logger.warning("data_cache: не удалось прочитать pg_stat_user_tables: %s", e)
        return None, None


def _refresh_db() -> None:
    global _db_version, _db_prices, _db_checked_at
    now = time.monotonic()
    if now - _db_checked_at >= DB_CHECK_SECONDS:
        data, prices = _read_db_counters()
        with _lock:
            _db_version, _db_prices = data, prices
            _db_checked_at = now


def data_version() -> tuple:
    _refresh_db()
    return (_local_version, _db_version, date.today())


def price_version() -> tuple:
    _refresh_db()
    return (_local_prices, _db_prices)


def version() -> tuple:
    """Полная версия: данные и цены. По ней прогрев решает, считать ли заново."""
    return (*data_version(), *price_version())


def cached(key: Hashable, compute: Callable[[], Any]) -> Any:
    """Результат `compute()` для текущей версии данных.

    Версия берётся до расчёта: если данные поменялись, пока он шёл, следующий
    запрос посчитает заново, а не отдаст результат из середины правки.
    Одинаковые запросы, пришедшие одновременно, считаются один раз.
    """
    hit = _usable(_store.get(key))
    if hit is not _MISS:
        return hit
    with _lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        hit = _usable(_store.get(key))
        if hit is not _MISS:
            return hit
        data, prices = data_version(), price_version()
        value = compute()
        with _lock:
            _store[key] = (data, prices, time.monotonic(), value)
            _store.move_to_end(key)
            while len(_store) > MAX_ENTRIES:
                old, _ = _store.popitem(last=False)
                _key_locks.pop(old, None)
        return value


def _usable(entry):
    """Значение записи, если его ещё можно отдать; иначе `_MISS`.

    Данные те же и цены те же — отдать. Данные те же, а цены сменились —
    отдать, пока запись не старше `PRICE_STALE_SECONDS`: прогрев её скоро
    перепишет. Сменились данные — считать заново.
    """
    if entry is None:
        return _MISS
    data, prices, at, value = entry
    if data != data_version():
        return _MISS
    if prices == price_version():
        return value
    if not getattr(_strict, "on", False) and time.monotonic() - at <= PRICE_STALE_SECONDS:
        return value
    return _MISS


@contextmanager
def refreshing():
    """Внутри блока записи по прежним ценам считаются заново.

    Так работает прогрев: посетители в это время получают прежний ответ
    из памяти, а прогрев пересчитывает его под новые цены и подменяет.
    """
    _strict.on = True
    try:
        yield
    finally:
        _strict.on = False


def cached_route(name: str, *key_args: str) -> Callable:
    """Обёртка для обработчика: ответ кэшируется по имени и параметрам.

    FastAPI читает сигнатуру через `__wrapped__`, так что зависимости и
    параметры запроса остаются как были. Обработчик можно звать и из кода —
    с именованными аргументами, как это делает FastAPI.
    """
    def decorate(fn: Callable) -> Callable:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            key = (name, *(_hashable(bound.arguments.get(a)) for a in key_args))
            return cached(key, lambda: fn(*args, **kwargs))
        return wrapper
    return decorate


def _hashable(value: Any) -> Hashable:
    # Из кода обработчик могут позвать без параметра — тогда в нём лежит
    # объект Query(...) со значением по умолчанию.
    default = getattr(value, "default", value)
    try:
        hash(default)
        return default
    except TypeError:
        return repr(default)


def clear() -> None:
    with _lock:
        _store.clear()
        _key_locks.clear()


def stats() -> dict:
    return {"entries": len(_store), "version": list(map(str, version()))}


# ── Отслеживание своих записей ────────────────────────────────────────────


def _table_of(obj: Any) -> str | None:
    table = getattr(obj, "__table__", None)
    return getattr(table, "name", None)


def _touches_data(tables: set[str | None]) -> bool:
    return any(t is None or t not in IGNORED_TABLES for t in tables)


def _price_only_update(obj: Any) -> bool:
    """Правка компании, задевшая только ценовые столбцы."""
    from sqlalchemy import inspect as sa_inspect

    if _table_of(obj) != "companies":
        return False
    changed = {
        attr.key for attr in sa_inspect(obj).attrs
        if attr.history.has_changes()
    }
    return bool(changed) and changed <= PRICE_COLUMNS


@event.listens_for(Session, "before_flush")
def _on_flush(session: Session, _ctx, _instances) -> None:
    created = {_table_of(o) for o in session.new} | {_table_of(o) for o in session.deleted}
    tables = set(created)
    for obj in session.dirty:
        if not session.is_modified(obj):
            continue
        if _price_only_update(obj):
            session.info[_PRICE_FLAG] = True
        else:
            tables.add(_table_of(obj))
    if "stock_prices" in tables:
        tables.discard("stock_prices")
        session.info[_PRICE_FLAG] = True
    if tables and _touches_data(tables):
        session.info[_FLAG] = True


@event.listens_for(Session, "do_orm_execute")
def _on_execute(state) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        table = getattr(getattr(state.statement, "table", None), "name", None)
        if table == "stock_prices":
            state.session.info[_PRICE_FLAG] = True
        elif _touches_data({table}):
            state.session.info[_FLAG] = True
        return
    if state.is_select:
        return
    # text(): по первому слову. Запись через text() — редкость, и лучше лишний
    # раз пересчитать, чем отдать устаревшее.
    sql = str(state.statement).lstrip().lower()
    if sql.startswith(("insert", "update", "delete", "truncate")):
        state.session.info[_FLAG] = True


@event.listens_for(Session, "after_commit")
def _on_commit(session: Session) -> None:
    if session.info.pop(_FLAG, False):
        bump()
    if session.info.pop(_PRICE_FLAG, False):
        bump_prices()


@event.listens_for(Session, "after_rollback")
def _on_rollback(session: Session) -> None:
    session.info.pop(_FLAG, None)
    session.info.pop(_PRICE_FLAG, None)
