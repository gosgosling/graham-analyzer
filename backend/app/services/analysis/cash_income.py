"""Касса отдельно от бизнеса — как у Грэма.

Грэм и Додд не смешивают два источника стоимости: то, что зарабатывает дело,
капитализируется множителем, а избыточные деньги считаются по балансу, рубль
за рубль. Процент с денег на счетах в первое не входит: деньги стоят своей
суммы, а не десяти годовых процентов, и умножать процентный доход на
множитель бизнеса значило бы заставить оценку гулять вслед за ключевой
ставкой. У Интер РАО ~270 млрд на счетах дают ~54 млрд процентов при ставке
20% и ~22 млрд при 8% — деньги те же, а «стоимость потока» отличается в два с
половиной раза.

Касса — это деньги и эквиваленты плюс депозиты и облигации
(`cash_investments`): проценты приносят и те и другие, и вычитать доход
только с одной части значило бы недосчитать кассу. У Интер РАО помимо
денег на балансе лежат облигации, доход с которых идёт отдельной строкой.

Отсюда правило для компании с чистой кассой (касса больше долга):
    · из прибыли — полученные проценты после налога;
    · из потока — те же проценты, если они стоят в операционной деятельности;
    · к цене бизнеса — капитализация минус чистая касса;
    · к стоимости — плюс чистая касса на акцию.

Второй пункт нужен потому, что МСФО (IAS 7) разрешает показывать полученные
проценты и в операционной, и в инвестиционной деятельности. У ЛУКОЙЛа 90 млрд
сидят в операционном потоке, у Интер РАО — в инвестиционном. Без поправки
поток одной компании их содержал бы, другой — нет.

**Правило включается только там, где проценты заведены.** Пустое поле
значит «не разносили», и тогда компания считается по-прежнему: вычесть кассу
из цены, не вычистив доход от неё из прибыли, — значит учесть её дважды.

Банк, биржа и гибрид не подпадают: деньги в их балансе — клиентские.
"""
from __future__ import annotations

from typing import Optional

# Налог на прибыль — общая ставка года. У ИТ-компании с льготой реальный налог
# на проценты может быть ниже, и тогда из прибыли вычитается чуть меньше
# дохода кассы, чем есть на деле. Расхождение — доли процента прибыли.
TAX_RATE_FROM_2025 = 0.25
TAX_RATE_BEFORE_2025 = 0.20

# Типы компаний, чьи деньги — не их собственные.
CLIENT_MONEY_TYPES = ("lender", "bank", "exchange", "hybrid", "insurance")


def tax_rate(year: int) -> float:
    return TAX_RATE_FROM_2025 if year >= 2025 else TAX_RATE_BEFORE_2025


def _f(value) -> Optional[float]:
    return None if value is None else float(value)


def own_money(company_type: Optional[str], report_type: Optional[str] = None) -> bool:
    """Деньги в балансе — собственные компании, а не клиентов."""
    kinds = {str(company_type or "").lower(), str(report_type or "").lower()}
    return not any(k.endswith(t) for k in kinds for t in CLIENT_MONEY_TYPES if k)


def net_cash(cash, debt, investments=None) -> Optional[float]:
    """Чистая касса, млн: деньги, депозиты и облигации минус долг. Не ниже 0."""
    cash = _f(cash)
    if cash is None:
        return None
    cash += _f(investments) or 0.0
    return max(cash - (_f(debt) or 0.0), 0.0)


def separates(report, company_type: Optional[str] = None) -> bool:
    """Считать ли кассу отдельно для этого отчёта.

    Три условия, все обязательны: деньги собственные, кассы больше долга и
    полученные проценты заведены. Без последнего отделить доход кассы от
    дохода бизнеса нечем.
    """
    if report is None or getattr(report, "interest_received", None) is None:
        return False
    if not own_money(company_type, getattr(report, "report_type", None)):
        return False
    cash = net_cash(
        getattr(report, "cash_and_equivalents", None), getattr(report, "debt", None),
        getattr(report, "cash_investments", None),
    )
    return bool(cash and cash > 0)


def interest_in_flow(report) -> float:
    """Сколько процентов сидит в операционном потоке, млн (в валюте отчёта)."""
    if not getattr(report, "interest_received_in_ocf", False):
        return 0.0
    return _f(getattr(report, "interest_received", None)) or 0.0


def interest_after_tax(report, year: int) -> float:
    """Доход кассы в прибыли, после налога, млн (в валюте отчёта)."""
    received = _f(getattr(report, "interest_received", None)) or 0.0
    return received * (1.0 - tax_rate(year))
