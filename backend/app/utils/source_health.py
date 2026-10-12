"""Предохранитель для внешних источников данных.

Когда T-Invest лежит (в октябре 2026 года — из-за атак на дата-центры
Яндекса), каждый запрос к нему висит до таймаута, а запросов много: цены раз
в минуту прогрева кэша, дивиденды по каждой бумаге, облигации по каждой
странице. Сайт от этого не падает, но всё, что зовёт брокера, медленно и
бессмысленно ждёт ответа, которого не будет.

Предохранитель запоминает сбой и на время паузы отвечает «недоступен» сразу,
не трогая сеть. Пауза растёт, пока сбои повторяются (1, 2, 4… до 30 минут), и
сбрасывается первым успешным ответом. Состояние живёт в процессе: после
перезапуска первый же вызов снова проверит источник, и это правильно.

Состояние видно в админке (`GET /admin/data-sources`): «молчит с 14:02,
следующая попытка в 14:10, последняя ошибка такая-то» полезнее, чем пустые
цены без объяснения.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Optional

BASE_COOLDOWN = timedelta(minutes=1)
MAX_COOLDOWN = timedelta(minutes=30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SourceBreaker:
    """Состояние одного внешнего источника."""

    name: str
    label: str
    clock: Callable[[], datetime] = field(default=_now, repr=False)
    failures: int = 0
    down_until: Optional[datetime] = None
    last_ok: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def available(self) -> bool:
        """Можно ли сейчас обращаться к источнику."""
        with self._lock:
            return self.down_until is None or self.clock() >= self.down_until

    def success(self) -> None:
        with self._lock:
            self.failures = 0
            self.down_until = None
            self.last_ok = self.clock()

    def failure(self, error: object) -> None:
        with self._lock:
            self.failures += 1
            now = self.clock()
            pause = min(BASE_COOLDOWN * (2 ** (self.failures - 1)), MAX_COOLDOWN)
            self.down_until = now + pause
            self.last_failure = now
            self.last_error = str(error)[:300]

    def status(self) -> dict:
        with self._lock:
            now = self.clock()
            down = self.down_until is not None and now < self.down_until
            return {
                "name": self.name,
                "label": self.label,
                "state": "down" if down else ("degraded" if self.failures else "ok"),
                "failures_in_row": self.failures,
                "retry_at": self.down_until.isoformat() if down else None,
                "last_ok": self.last_ok.isoformat() if self.last_ok else None,
                "last_failure": self.last_failure.isoformat() if self.last_failure else None,
                "last_error": self.last_error,
            }


_registry: Dict[str, SourceBreaker] = {}
_registry_lock = threading.Lock()


def breaker(name: str, label: str = "") -> SourceBreaker:
    """Один предохранитель на источник на весь процесс."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = SourceBreaker(name=name, label=label or name)
        return _registry[name]


def all_statuses() -> list:
    with _registry_lock:
        items = list(_registry.values())
    return [b.status() for b in sorted(items, key=lambda b: b.name)]


# Источники, у которых предохранитель есть. Заведены заранее, чтобы админка
# показывала их и до первого обращения.
TINVEST = breaker("tinvest", "T-Invest API (цены, дивиденды, облигации, справочник)")
MOEX_LIVE = breaker("moex_live", "MOEX ISS — текущие цены (резерв)")
