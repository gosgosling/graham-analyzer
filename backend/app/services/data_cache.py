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
"""
from __future__ import annotations

import functools
import inspect
import logging
import threading
import time
from collections import OrderedDict
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

# Как часто спрашивать у Postgres чужие записи. Запрос дешёвый (~5 мс), но
# на каждый ответ из кэша его делать незачем.
DB_CHECK_SECONDS = 2.0
MAX_ENTRIES = 2000

_lock = threading.Lock()
_local_version = 0
_db_version: int | None = None
_db_checked_at = 0.0

_store: "OrderedDict[Hashable, tuple[tuple, Any]]" = OrderedDict()
_key_locks: dict[Hashable, threading.Lock] = {}

_FLAG = "ga_data_changed"


def bump() -> None:
    """Данные изменились — все результаты устарели."""
    global _local_version
    with _lock:
        _local_version += 1


def _read_db_counter() -> int | None:
    try:
        with engine.connect() as conn:
            value = conn.execute(
                text(
                    "select coalesce(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) "
                    "from pg_stat_user_tables where not (relname = any(:ignored))"
                ),
                {"ignored": list(IGNORED_TABLES)},
            ).scalar()
            return int(value or 0)
    except Exception as e:  # статистика — подстраховка, без неё кэш тоже работает
        logger.warning("data_cache: не удалось прочитать pg_stat_user_tables: %s", e)
        return None


def version() -> tuple:
    global _db_version, _db_checked_at
    now = time.monotonic()
    if now - _db_checked_at >= DB_CHECK_SECONDS:
        counter = _read_db_counter()
        with _lock:
            _db_version = counter
            _db_checked_at = now
    return (_local_version, _db_version, date.today())


def cached(key: Hashable, compute: Callable[[], Any]) -> Any:
    """Результат `compute()` для текущей версии данных.

    Версия берётся до расчёта: если данные поменялись, пока он шёл, следующий
    запрос посчитает заново, а не отдаст результат из середины правки.
    Одинаковые запросы, пришедшие одновременно, считаются один раз.
    """
    current = version()
    hit = _store.get(key)
    if hit is not None and hit[0] == current:
        return hit[1]
    with _lock:
        key_lock = _key_locks.setdefault(key, threading.Lock())
    with key_lock:
        current = version()
        hit = _store.get(key)
        if hit is not None and hit[0] == current:
            return hit[1]
        value = compute()
        with _lock:
            _store[key] = (current, value)
            _store.move_to_end(key)
            while len(_store) > MAX_ENTRIES:
                old, _ = _store.popitem(last=False)
                _key_locks.pop(old, None)
        return value


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


@event.listens_for(Session, "before_flush")
def _on_flush(session: Session, _ctx, _instances) -> None:
    tables = {_table_of(o) for o in session.new} | {_table_of(o) for o in session.deleted}
    tables |= {_table_of(o) for o in session.dirty if session.is_modified(o)}
    if tables and _touches_data(tables):
        session.info[_FLAG] = True


@event.listens_for(Session, "do_orm_execute")
def _on_execute(state) -> None:
    if state.is_insert or state.is_update or state.is_delete:
        table = getattr(getattr(state.statement, "table", None), "name", None)
        if _touches_data({table}):
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


@event.listens_for(Session, "after_rollback")
def _on_rollback(session: Session) -> None:
    session.info.pop(_FLAG, None)
