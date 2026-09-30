"""История цены акции для графика на карточке компании.

График строится не по годам, а по торговым дням: годовая точка скрывает
ровно то, ради чего на график и смотрят — как цена ходила внутри года
относительно того, что компания зарабатывала.

**Наложения считаются здесь, а не на фронте.** P/E за каждый день — это
дневная цена, делённая на прибыль на акцию того отчёта, который на ту дату
был опубликован. Знание о том, какой отчёт когда вышел, живёт в бэкенде, и
тащить его на фронт ради деления значило бы продублировать там же и правило
«отчёт за 2024 год становится известен весной 2025-го».

Это правило здесь главное. Множитель, посчитанный по отчёту, которого на ту
дату ещё не существовало, — это заглядывание вперёд: на графике вышло бы,
что рынок знал о прибыли за полгода до её публикации.
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.financial_report import FinancialReport
from app.models.multiplier import Multiplier
from app.models.stock_price import StockPrice
from app.utils.per_share import per_share

router = APIRouter(prefix="/companies", tags=["prices"])
# Сколько ждать публикации годового отчёта после конца периода. По российским
# правилам раскрытия эмитент обязан опубликовать годовую отчётность МСФО в
# течение 120 дней; крупные компании укладываются в март-апрель.
PUBLICATION_LAG = timedelta(days=120)

# Насколько `report_date` должна отстоять от конца периода, чтобы её можно было
# принять за дату публикации.
#
# **Поле `report_date` в этой базе — дата баланса, а не публикации.** У 1204
# годовых отчётов из 1210 там стоит 31 декабря. Доверять ему значило бы
# объявить, что рынок знал годовую прибыль тридцать первого декабря — то есть
# построить кривую множителя на заглядывании вперёд длиной в четыре месяца.
# Поэтому дата принимается только если она отстоит от конца периода настолько,
# что публикацией быть могла.
PUBLICATION_MIN_LAG = timedelta(days=30)


def _published_on(report: FinancialReport) -> date:
    """Когда отчёт стал известен рынку.

    Ошибиться здесь в большую сторону безопаснее, чем в меньшую: лишний месяц
    задержки сдвинет ступеньку на кривой, а заглядывание вперёд сделает саму
    кривую ложной.
    """
    period_end = date(int(report.fiscal_year), 12, 31)
    if (report.report_date is not None
            and report.report_date - period_end >= PUBLICATION_MIN_LAG):
        return report.report_date
    return period_end + PUBLICATION_LAG


def _gap(mark: Optional[dict], field: str) -> Optional[str]:
    """Причина, по которой множителя за этот день нет. None — множитель есть."""
    if mark is None:
        return "первый годовой отчёт ещё не опубликован"
    value = mark[field]
    if value is None:
        return (f"в отчёте за {mark['year']} год нет "
                f"{'прибыли' if field == 'eps' else 'капитала'}")
    if value <= 0:
        return (f"за {mark['year']} год {'убыток' if field == 'eps' else 'капитал отрицателен'}"
                f" — множитель не определён")
    return None


@router.get("/{company_id}/prices")
def price_history(
    company_id: int,
    since: Optional[date] = Query(None, description="с какой даты, по умолчанию вся"),
    db: Session = Depends(get_db),
) -> dict:
    """Дневные цены закрытия плюс ряды множителей на те же даты."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")

    query = db.query(StockPrice).filter(StockPrice.company_id == company_id)
    if since is not None:
        query = query.filter(StockPrice.date >= since)
    prices = query.order_by(StockPrice.date).all()

    if not prices:
        return {
            "company": {"id": company.id, "ticker": company.ticker, "name": company.name},
            "points": [], "reports": [], "summary": None,
        }

    # Прибыль и капитал на акцию берутся из мультипликаторов по отчётам — из
    # того же источника, что и таблица под графиком, а не из отчёта напрямую.
    #
    # Сперва здесь делилось `net_income_reported` на `shares_issued` из самого
    # отчёта, и график разошёлся с таблицей в трёх местах сразу:
    #   · ЛУКОЙЛ до 2014 года отчитывался в долларах — мультипликатор это
    #     пересчитывает, а прямое деление давало EPS около 10 ₽ вместо 443;
    #   · у Сбера за 2016 и 2018 годы пуста отчётная прибыль, за 2021 и 2022 —
    #     число размещённых акций, и отчёт выпадал целиком, а множитель на
    #     графике держался на отчёте трёхлетней давности;
    #   · оценка у нас ведётся по акциям в обращении, а прямое деление брало
    #     размещённые.
    # Мультипликатор всё это уже разрешил: валюту, число акций, запасные поля.
    # Считать то же самое второй раз и по-другому значило бы рисовать над
    # таблицей числа, которые с ней не сходятся.
    rows = (
        db.query(Multiplier, FinancialReport)
        .join(FinancialReport, Multiplier.report_id == FinancialReport.id)
        .filter(
            Multiplier.company_id == company_id,
            Multiplier.type == "report_based",
            FinancialReport.period_type == "ANNUAL",
        )
        .all()
    )

    marks = []
    for mult, report in sorted(rows, key=lambda pair: _published_on(pair[1])):
        shares = float(mult.shares_used) if mult.shares_used else None
        eps = float(mult.eps) if mult.eps is not None else None
        equity = float(mult.equity) if mult.equity is not None else None
        marks.append({
            "published": _published_on(report),
            "year": int(report.fiscal_year),
            "eps": eps,
            "bvps": (equity * 1_000_000 / shares) if equity and shares else None,
        })

    points = []
    cursor = -1
    for row in prices:
        # Курсор двигается вперёд вместе с датами — ряд уже отсортирован, и
        # искать подходящий отчёт заново для каждого дня незачем.
        while cursor + 1 < len(marks) and marks[cursor + 1]["published"] <= row.date:
            cursor += 1
        price = float(row.price)
        mark = marks[cursor] if cursor >= 0 else None
        points.append({
            "date": row.date.isoformat(),
            "price": per_share(price),
            "pe": (round(price / mark["eps"], 2)
                   if mark and mark["eps"] and mark["eps"] > 0 else None),
            "pb": (round(price / mark["bvps"], 2)
                   if mark and mark["bvps"] and mark["bvps"] > 0 else None),
            "basis_year": mark["year"] if mark else None,
            # Почему множителя нет. Пропуск без причины на графике выглядит
            # как сбой, а причины здесь ровно три, и все — про компанию или
            # отчётность, а не про расчёт.
            "pe_gap": _gap(mark, "eps"),
            "pb_gap": _gap(mark, "bvps"),
        })

    values = [p["price"] for p in points]
    return {
        "company": {"id": company.id, "ticker": company.ticker, "name": company.name},
        "points": points,
        # Даты публикаций нужны графику отдельно: по ним рисуются засечки, и
        # без них ступеньки на кривой множителя выглядят как сбой данных.
        "reports": [
            {"year": m["year"], "published": m["published"].isoformat(),
             "eps": per_share(m["eps"]),
             "bvps": per_share(m["bvps"]) if m["bvps"] else None}
            for m in marks
        ],
        "summary": {
            "from": points[0]["date"],
            "till": points[-1]["date"],
            "count": len(points),
            "min": min(values),
            "max": max(values),
            "last": values[-1],
            "average": per_share(sum(values) / len(values)),
        },
    }
