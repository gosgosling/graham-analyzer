"""Базовый множитель рынка — данные для страницы разбора.

Эндпоинт отдаёт не одно число, а весь путь к нему: что взято из отчётов, что
выведено арифметикой, а что назначено суждением. Разделение существенно —
страница обязана показывать его явно, иначе множитель прочитается как
измерение, каковым он на две трети не является.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.market_assumption import MarketAssumption
from app.models.company import Company
from app.services.analysis import market_snapshot
from app.services.analysis.company_valuation import DEFAULT_WINDOW, assess, series
from app.services.analysis.market_multiple import (
    HISTORIC_AVERAGE,
    HISTORIC_RANGE,
    SP400_1987,
    base_multiple,
    implied_growth,
    implied_premium,
    paired_multiples,
    payout_ladder,
    sensitivity,
)

router = APIRouter(prefix="/valuation", tags=["valuation"])


def _assumption(db: Session, year: Optional[int]) -> MarketAssumption:
    query = db.query(MarketAssumption)
    row = (
        db.get(MarketAssumption, year) if year is not None
        else query.order_by(MarketAssumption.year.desc()).first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Допущений об уровне рынка нет. Задайте их командой "
                "python -m scripts.set_market_assumption"
            ),
        )
    return row


def _implied(snapshot, assumption) -> dict:
    """Что рынок закладывает в текущую цену.

    Обратный ход формулы: вместо того чтобы назначить величину и удивляться
    расхождению с ценой, спрашиваем, какое значение уже сидит в цене.
    """
    payout, multiple = snapshot.payout, snapshot.observed_multiple
    risk_free = float(assumption.risk_free_rate)
    premium = float(assumption.risk_premium)
    growth = float(assumption.dividend_growth)

    # Третий разворот: какую долгосрочную ставку подразумевает цена, если
    # премия и рост приняты. Считается прямо здесь — отдельная функция ради
    # одного вычитания не нужна.
    implied_rate = None
    if payout and multiple:
        implied_rate = round(payout / multiple + growth - premium, 2)

    return {
        "growth_at_stated_premium": implied_growth(payout, risk_free, premium, multiple),
        "premium_at_stated_growth": implied_premium(payout, risk_free, growth, multiple),
        "risk_free_at_stated_premium_and_growth": implied_rate,
    }


@router.get("/market-multiple")
def market_multiple(
    year: Optional[int] = Query(None, description="год допущений; по умолчанию последний"),
    data_year: int = Query(market_snapshot.DEFAULT_YEAR, description="год данных о выплате"),
    db: Session = Depends(get_db),
) -> dict:
    assumption = _assumption(db, year)
    snapshot = market_snapshot.snapshot(db, data_year)

    payout = (
        float(assumption.payout) if assumption.payout is not None else snapshot.payout
    )
    normalized = (
        float(assumption.normalized_risk_free_rate)
        if assumption.normalized_risk_free_rate is not None else None
    )
    pair = paired_multiples(
        payout,
        float(assumption.risk_free_rate),
        float(assumption.risk_premium),
        float(assumption.dividend_growth),
        normalized,
    )

    return {
        "assumption": {
            "year": assumption.year,
            "risk_free_rate": float(assumption.risk_free_rate),
            "normalized_risk_free_rate": normalized,
            "risk_premium": float(assumption.risk_premium),
            "dividend_growth": float(assumption.dividend_growth),
            "payout": float(assumption.payout) if assumption.payout is not None else None,
            "payout_used": payout,
            "payout_from_data": assumption.payout is None,
            "note": assumption.note,
            "source": assumption.source,
        },
        "snapshot": snapshot.as_dict(),
        "current": pair["current"].as_dict() if pair["current"] else None,
        "normalized": pair["normalized"].as_dict() if pair["normalized"] else None,
        "rate_effect": pair["rate_effect"],
        "sensitivity": sensitivity(pair["current"]) if pair["current"] else [],
        # Лестница выплаты: рост на каждой ступени свой, потому что расти
        # можно только на то, что не раздал.
        "payout_ladder": payout_ladder(
            snapshot.roe,
            float(assumption.risk_free_rate),
            float(assumption.risk_premium),
            normalized,
        ),
        "implied": _implied(snapshot, assumption),
        "reference": {
            "book": SP400_1987,
            "book_multiple": base_multiple(**SP400_1987).value,
            "historic_average": HISTORIC_AVERAGE,
            "historic_range": list(HISTORIC_RANGE),
        },
    }


@router.get("/company/{company_id}")
def company_valuation(
    company_id: int,
    window: int = Query(DEFAULT_WINDOW, ge=3, le=15, description="окно нормализации, лет"),
    year: Optional[int] = Query(None, description="год допущений; по умолчанию последний"),
    db: Session = Depends(get_db),
) -> dict:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return assess(db, company, _assumption(db, year), window)


@router.get("/company/{company_id}/series")
def company_series(
    company_id: int,
    window: int = Query(DEFAULT_WINDOW, ge=3, le=15, description="окно нормализации, лет"),
    db: Session = Depends(get_db),
) -> dict:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")
    return series(db, company, window)


# ── Свод для карточки ──────────────────────────────────────────────────────

# Окна нормализации, которые показываются рядом. Три, а не четыре: у Грэма
# каждое отвечает на свой вопрос — три года «дорого ли сейчас», семь «сколько
# стоит», десять «что было за цикл», — и пятилетнее из них выпадает, оно
# промежуточное и своего вопроса не имеет.
SUMMARY_WINDOWS = (3, 7, 10)

# Ставки для сетки, процентов годовых. Первой всегда идёт сегодняшняя — она не
# здесь, а в допущениях рынка. Остальные — не прогноз, а вопрос «сколько будет
# стоить эта же компания, если деньги подешевеют»: при спреде `K − g` в
# знаменателе разница между 16% и 10% меняет оценку в полтора раза, и увидеть
# это важнее, чем поверить в любую отдельную цифру.
SUMMARY_RATES = (16.0, 13.0, 10.0, 8.0)


class _RateShim:
    """Допущения рынка с подменённой безрисковой ставкой.

    Сетка считается тем же `assess`, что и основная оценка, — иначе она
    показывала бы числа, полученные другим способом, и расходилась бы с
    карточкой по причинам, которых читатель не увидит.
    """

    def __init__(self, base, risk_free_rate: float):
        self.year = base.year
        self.risk_free_rate = risk_free_rate
        self.risk_premium = base.risk_premium
        self.dividend_growth = base.dividend_growth
        self.payout = base.payout
        self.long_run_growth = getattr(base, "long_run_growth", None)
        self.note = getattr(base, "note", None)
        self.source = getattr(base, "source", None)


def _headline(payload: dict) -> dict:
    """Какую ступень показывать как оценку окна и по какой величине.

    Лестница прибыли — первая по праву: это та величина, которую оценивает
    формула гл. 32, и та, с которой сопоставим купон облигации.

    Но она бывает пуста. У Аэрофлота на десятилетнем окне нормальная прибыль
    отрицательна — там годы ковида и двадцать второй, — а денежная ступень
    жива, и полоса из неё получается. Опорная цена в таком случае падает на
    низ полосы, то есть считается по другой лестнице. Показывать рядом
    «оценка — ₽» и «опорная цена 27 ₽» нельзя: числа противоречат друг другу
    на вид и оба верны по отдельности. Поэтому ступень называется явно.
    """
    band = payload.get("band") or {}
    ladders = band.get("ladders", [])
    for ladder in ladders:
        if ladder["name"] == "прибыль":
            return {"value": ladder["value"],
                    "normal": ladder["normal_per_share"],
                    "ladder": ladder["name"]}
    if ladders:
        best = max(ladders, key=lambda item: item["value"])
        return {"value": best["value"],
                "normal": best["normal_per_share"],
                "ladder": best["name"]}
    return {"value": None, "normal": None, "ladder": None}


@router.get("/company/{company_id}/summary")
def company_summary(
    company_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Компактный свод: три окна, сетка ставок, опорная цена с запасом.

    Отдельно от `/company/{id}`, потому что отвечает на другой вопрос. Там —
    одна настройка во всех подробностях; здесь — как ответ меняется от того,
    что мы в него подставили. Держать это в одном ответе значило бы считать
    оценку восемь раз всем, кому нужна одна.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")

    base = _assumption(db, None)
    current = assess(db, company, base, DEFAULT_WINDOW)
    if not current.get("available"):
        return {"available": False, "reason": current.get("reason")}

    windows = []
    for window in SUMMARY_WINDOWS:
        payload = assess(db, company, base, window)
        band = payload.get("band") or {}
        safety = payload.get("safety") or {}
        windows.append({
            "window": window,
            "refused": bool(band.get("refused")),
            "reason": band.get("reason"),
            "method": band.get("method"),
            # Нормальная прибыль на акцию — то, что делится на цену. Ради неё
            # окна и сравниваются: у ЛУКОЙЛа за три года выходит одно, за
            # десять другое, и расхождение само по себе есть сообщение.
            "normal_earnings": _headline(payload)["normal"],
            "value": _headline(payload)["value"],
            # Название ступени, по которой посчитана оценка окна. Пусто, когда
            # это обычная лестница прибыли, — подписывать её незачем.
            "ladder": (_headline(payload)["ladder"]
                       if _headline(payload)["ladder"] != "прибыль" else None),
            "reference": safety.get("reference"),
            "margin": safety.get("value_margin"),
            "signal": safety.get("signal"),
            "label": safety.get("label"),
        })

    rates = []
    for rate in SUMMARY_RATES:
        payload = assess(db, company, _RateShim(base, rate), DEFAULT_WINDOW)
        band = payload.get("band") or {}
        safety = payload.get("safety") or {}
        rates.append({
            "risk_free_rate": rate,
            "required_return": rate + float(base.risk_premium),
            "multiple": band.get("multiple_high"),
            "value": _headline(payload)["value"],
            "reference": safety.get("reference"),
            "margin": safety.get("value_margin"),
            "refused": bool(band.get("refused")),
        })

    safety = current.get("safety") or {}
    return {
        "available": True,
        "price": current.get("price"),
        "window": DEFAULT_WINDOW,
        "assumption": {
            "risk_free_rate": float(base.risk_free_rate),
            "risk_premium": float(base.risk_premium),
        },
        "windows": windows,
        "rates": rates,
        "safety": safety,
        "band": {
            "low": (current.get("band") or {}).get("low"),
            "high": (current.get("band") or {}).get("high"),
            "conservative": (current.get("band") or {}).get("conservative"),
            "method": (current.get("band") or {}).get("method"),
            "refused": bool((current.get("band") or {}).get("refused")),
            "reason": (current.get("band") or {}).get("reason"),
        },
    }


@router.get("/company/{company_id}/history")
def company_valuation_history(
    company_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Оценка по годам — та, что получалась бы тогда, а не сегодняшняя.

    Это ряд из обратного теста, вынесенный на график. Ценность его в том, чего
    не видно у горизонтальной черты: у ЛУКОЙЛа за 2022 год полоса шла
    4 691–5 885 при цене 4 072 — то есть акция стоила дешевле своей тогдашней
    оценки, а не сегодняшней. Черта, проведённая по нынешнему расчёту, об этом
    сказать не может: она знает прибыль 2025 года и знает сегодняшнюю ставку.

    **Заглядывания вперёд нет.** За каждый год берётся ряд, обрезанный по этот
    год, тогдашняя балансовая стоимость и ключевая ставка того года — всё это
    уже устроено в `valuation_backtest`, здесь только вызов.

    **Дата, с которой оценка становится известной, — не конец года.** Отчёт за
    2022-й выходит весной 2023-го, и до тех пор посчитать по нему было нечего.
    Поэтому каждая ступень начинается с даты раскрытия: иначе график
    утверждал бы, что оценка была доступна за четыре месяца до отчёта.
    """
    from app.models.key_rate import KeyRate
    from app.routers.prices_router import PUBLICATION_LAG
    from app.services.analysis.valuation_backtest import OFZ_OVER_KEY_RATE, backtest

    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Компания {company_id} не найдена")

    assumption = _assumption(db, None)
    rates = {row.year: float(row.avg_rate) for row in db.query(KeyRate)}

    # **Ставка сдвинута на год вперёд, и это не то же самое, что в гейте.**
    #
    # Гейт сравнивает оценку за год Y с ценой того же года Y, и ставка ему
    # нужна тоже за год Y. На графике ступень живёт иначе: отчёт за 2022-й
    # выходит весной 2023-го и стоит до весны 2024-го, то есть ступень по
    # отчёту года Y покрывает год Y+1 целиком. Считать её по ставке года Y
    # значит показывать деньги прошлого года по цене позапрошлого.
    #
    # На данных это вышло наружу сразу: последняя ступень ЛУКОЙЛа покрывает
    # апрель 2026 — сегодня, но бралась по ключевой 2025 года (19,13%), и
    # опорная выходила 3 429 ₽ против 4 047 ₽ в карточке под тем же графиком.
    # Одна и та же величина двумя числами на одном экране.
    #
    # Для последней ступени ставка берётся из допущений рынка: она про
    # сегодня, и карточка считается по ней же.
    shifted = {
        year: rates.get(year + 1, float(assumption.risk_free_rate) - OFZ_OVER_KEY_RATE)
        for year in rates
    }

    result = backtest(
        db, company,
        risk_premium=float(assumption.risk_premium),
        key_rates=shifted,
        growth_cap=(
            float(assumption.long_run_growth)
            if getattr(assumption, "long_run_growth", None) is not None else None
        ),
    )

    years = []
    for row in result.years:
        known_from = date(row.year, 12, 31) + PUBLICATION_LAG
        years.append({
            "year": row.year,
            "known_from": known_from.isoformat(),
            "price": row.price,
            "low": row.low,
            "high": row.high,
            "conservative": row.conservative,
            "fair": row.fair,
            "method": row.method,
            "refused": row.refused,
            "inside": row.inside,
        })

    return {
        "ticker": result.ticker,
        "years": years,
        "hits": result.hits,
        "counted": len(result.counted),
        "verdict": result.verdict,
        "note": (
            f"ставка каждого года — ключевая ЦБ плюс {OFZ_OVER_KEY_RATE} п.п.; "
            f"премия за риск {float(assumption.risk_premium)}%"
        ),
    }
