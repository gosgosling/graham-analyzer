"""Ключевая ставка ЦБ: загрузка с сайта и ряд по дням для оценки.

Источник — таблица на сайте ЦБ (https://www.cbr.ru/hd_base/KeyRate/). ЦБ
печатает значение на каждый рабочий день; оно и хранится — в `key_rates_daily`
по дням и в `key_rates` средней за год.

Раньше загрузка жила только в скрипте и запускалась «раз в год, после закрытия
года». Для годовой средней этого хватало. Дневной ряд устаревает с первым же
решением ЦБ, поэтому загрузка вынесена сюда и зовётся из ежедневного
планировщика — ровно одним запросом за текущий год.
"""
from __future__ import annotations

import bisect
import logging
import re
import ssl
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.key_rate import KeyRate
from app.models.key_rate_daily import KeyRateDaily

logger = logging.getLogger(__name__)

_URL = (
    "https://www.cbr.ru/hd_base/KeyRate/"
    "?UniDbQuery.Posted=True&UniDbQuery.From={frm}&UniDbQuery.To={to}"
)
# Строка таблицы: дата и ставка в соседних ячейках.
_ROW = re.compile(r"<td[^>]*>\s*(\d{2}\.\d{2}\.\d{4})\s*</td>\s*<td[^>]*>\s*([\d,\.]+)\s*</td>")

# Ключевая ставка введена 13 сентября 2013 года; раньше её не существует.
FIRST_YEAR = 2013


def fetch_year(year: int, timeout: int = 30) -> List[Tuple[date, float]]:
    """Дневные значения ставки за год: [(дата, ставка), ...] по возрастанию."""
    url = _URL.format(frm=f"01.01.{year}", to=f"31.12.{year}")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    # Сертификат ЦБ подписан национальным УЦ, которого нет в системном хранилище
    # на большинстве машин: проверку отключаем осознанно — данные публичные,
    # и подмена ключевой ставки не создаёт угрозы.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        html = response.read().decode("utf-8", "replace")

    rows = [
        (datetime.strptime(day, "%d.%m.%Y").date(), float(rate.replace(",", ".")))
        for day, rate in _ROW.findall(html)
    ]
    return sorted(rows)


def average_rate(rows: List[Tuple[date, float]]) -> float:
    return round(sum(rate for _day, rate in rows) / len(rows), 2)


def store_year(db: Session, year: int, rows: List[Tuple[date, float]]) -> None:
    """Сохраняет дни года и пересчитывает среднюю за год."""
    if not rows:
        return
    existing = {
        row.date: row for row in db.query(KeyRateDaily).filter(
            KeyRateDaily.date >= date(year, 1, 1),
            KeyRateDaily.date <= date(year, 12, 31),
        )
    }
    for day, rate in rows:
        if day in existing:
            existing[day].rate = rate
        else:
            db.add(KeyRateDaily(date=day, rate=rate, source="cbr"))

    average = average_rate(rows)
    yearly = db.query(KeyRate).filter(KeyRate.year == year).first()
    if yearly:
        yearly.avg_rate = average
        yearly.source = "cbr"
    else:
        db.add(KeyRate(year=year, avg_rate=average, source="cbr"))
    db.commit()


def refresh_current_year(db: Session) -> int:
    """Докачивает текущий год. Для ежедневного планировщика: один запрос."""
    year = date.today().year
    try:
        rows = fetch_year(year)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Ключевая ставка ЦБ не загрузилась: %s", exc)
        return 0
    store_year(db, year, rows)
    return len(rows)


class RateSeries:
    """Ставка, действовавшая на любую дату, — по дневному ряду.

    Выходные и праздники в ряду ЦБ отсутствуют; на такой день действует
    ставка последнего рабочего дня. До введения ключевой ставки значения нет.
    """

    def __init__(self, rows: List[Tuple[date, float]]):
        self.days = [day for day, _ in rows]
        self.rates = [rate for _, rate in rows]

    @classmethod
    def load(cls, db: Session) -> "RateSeries":
        rows = db.query(KeyRateDaily.date, KeyRateDaily.rate).order_by(KeyRateDaily.date).all()
        return cls([(day, float(rate)) for day, rate in rows])

    def __bool__(self) -> bool:
        return bool(self.days)

    def on(self, day: date) -> Optional[float]:
        i = bisect.bisect_right(self.days, day) - 1
        return self.rates[i] if i >= 0 else None

    def trailing(self, day: date, days: int = 365, min_days: int = 120) -> Optional[float]:
        """Средняя ставка за `days` календарных дней до `day` включительно.

        Мерка денег, которую оценка на графике берёт вместо ставки конкретного
        дня. Проверено на истории: ставка на день раскрытия отчёта разрушала
        сигнал (цена ниже опорной → через два года −4%, выше → −3%), потому
        что пики вроде апреля 2015-го или 2022-го рынок смотрит насквозь.
        Средняя за 12 месяцев до раскрытия даёт +13% против −7% — лучше
        всего, что пробовали, и без заглядывания вперёд.

        Меньше `min_days` рабочих дней в окне — средней нет: осень 2013 года,
        когда ставка только введена, не описывает год.
        """
        lo = bisect.bisect_left(self.days, day - timedelta(days=days))
        hi = bisect.bisect_right(self.days, day)
        window = self.rates[lo:hi]
        if len(window) < min_days:
            return None
        return round(sum(window) / len(window), 4)

    def changes(self, start: date, end: date) -> List[Tuple[date, float]]:
        """Отрезки постоянной ставки внутри [start, end): [(с какого дня, ставка)].

        Первый отрезок начинается ровно в `start` со ставкой, действовавшей в
        тот день; дальше — по одному на каждое изменение.
        """
        first = self.on(start)
        segments: List[Tuple[date, float]] = []
        if first is not None:
            segments.append((start, first))
        i = bisect.bisect_right(self.days, start)
        last = first
        while i < len(self.days) and self.days[i] < end:
            if self.rates[i] != last:
                segments.append((self.days[i], self.rates[i]))
                last = self.rates[i]
            i += 1
        return segments
