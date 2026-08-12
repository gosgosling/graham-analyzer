"""
Роутер для рыночных данных.

Эндпоинты:
    GET  /market/price/moex?ticker=SBER&date=2024-12-31
    GET  /market/shares/moex?ticker=SBER
    GET  /market/dividends/moex?ticker=SBER&fiscal_year=2024
    POST /market/prices/backfill?company_id=1          — ручной бэкфилл цен
    POST /market/prices/backfill-all                   — бэкфилл для всех компаний
"""
from datetime import date as date_type
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.services.market.price_history_service import backfill_company_prices, backfill_all_companies
from app.services.share_splits import price_scale_hint, shares_at_date
from app.services.ticker_history import resolve_ticker
from app.utils.moex_client import (
    get_closing_price_on_or_before,
    get_first_trade_date,
    get_shares_outstanding,
    get_dividends_for_period,
    get_fx_rate_on_or_before,
)

router = APIRouter(prefix="/market", tags=["market"])


class MoexSharesResponse(BaseModel):
    ticker: str
    issuesize: int
    secname: str
    lotsize: int
    board: str
    note: str = (
        "Текущее значение из реестра Мосбиржи. "
        "Для точности проверьте значение в отчёте компании."
    )
    # Выпуск на отчётную дату: сегодняшний ISSUESIZE, поделённый на дробления,
    # случившиеся после неё. Пусто — сплитов не было и делить нечего.
    issuesize_at_date: Optional[int] = None
    # Пояснение про смену масштаба — показывается рядом со значением.
    split_note: Optional[str] = None


@router.get(
    "/shares/moex",
    response_model=MoexSharesResponse,
    summary="Количество акций компании (ISSUESIZE) на Мосбирже",
    description=(
        "Возвращает количество выпущенных акций из реестра Мосбиржи (ISSUESIZE). "
        "Это текущее значение — исторические данные по количеству акций MOEX не предоставляет. "
        "Подходит для автозаполнения при вводе отчётов, так как выпуск акций меняется редко."
    ),
)
def get_moex_shares(
    ticker: str = Query(..., description="Тикер (SECID) на Мосбирже, например: SBER, GAZP"),
    company_id: Optional[int] = Query(
        None, description="ID компании — нужен, чтобы учесть дробления акций",
    ),
    date: Optional[str] = Query(
        None,
        description=(
            "Отчётная дата YYYY-MM-DD. Реестр Мосбиржи отдаёт выпуск на "
            "сегодня; с этой датой ответ дополняется выпуском, действовавшим "
            "тогда — после сплита это разные числа."
        ),
    ),
    db: Session = Depends(get_db),
):
    result = get_shares_outstanding(ticker.upper())

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Количество акций для тикера '{ticker}' не найдено. "
                "Проверьте тикер или введите значение вручную."
            ),
        )

    target_date: Optional[date_type] = None
    if date:
        try:
            target_date = date_type.fromisoformat(date)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Неверный формат даты: '{date}'. Используйте YYYY-MM-DD.",
            )

    splits = None
    if company_id is not None:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company is not None:
            splits = company.share_splits

    return MoexSharesResponse(
        ticker=result["ticker"],
        issuesize=result["issuesize"],
        secname=result["secname"],
        lotsize=result["lotsize"],
        board=result["board"],
        issuesize_at_date=shares_at_date(result["issuesize"], splits, target_date),
        split_note=price_scale_hint(splits, target_date),
    )


class DividendPayment(BaseModel):
    registryclosedate: str
    value: float
    currency: str


class MoexDividendsResponse(BaseModel):
    ticker: str
    fiscal_year: int
    period_type: str
    fiscal_quarter: Optional[int]
    period_from: str
    period_till: str
    total: float          # суммарные дивиденды на акцию
    currency: str
    payments: list[DividendPayment]
    payments_count: int
    note: str


@router.get(
    "/dividends/moex",
    response_model=MoexDividendsResponse,
    summary="Дивиденды компании с Мосбиржи за отчётный период",
    description=(
        "Возвращает дивидендные выплаты по тикеру за указанный отчётный период. "
        "Для годовых отчётов суммируются все выплаты, чья дата закрытия реестра "
        "попадает в отчётный год. Для квартальных — только выплаты в соответствующем квартале "
        "(у большинства российских компаний за квартал дивидендов нет — это нормально)."
    ),
)
def get_moex_dividends(
    ticker: str = Query(..., description="Тикер (SECID), например: SBER, LKOH"),
    fiscal_year: int = Query(..., ge=1990, le=2100, description="Финансовый год"),
    period_type: str = Query("annual", description="Тип периода: annual | quarterly | semi_annual"),
    fiscal_quarter: Optional[int] = Query(None, ge=1, le=4, description="Квартал (1-4), только для quarterly"),
):
    if period_type not in ("annual", "quarterly", "semi_annual"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_type должен быть: annual, quarterly или semi_annual",
        )
    if period_type == "quarterly" and fiscal_quarter is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Для quarterly необходимо указать fiscal_quarter (1-4)",
        )

    result = get_dividends_for_period(
        ticker=ticker.upper(),
        fiscal_year=fiscal_year,
        period_type=period_type,
        fiscal_quarter=fiscal_quarter,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Не удалось получить дивиденды для '{ticker}' с Мосбиржи. "
                "Проверьте тикер."
            ),
        )

    # Формируем человекочитаемую заметку
    if result["payments"]:
        dates = ", ".join(p["registryclosedate"] for p in result["payments"])
        note = (
            f"Найдено {len(result['payments'])} выплат(а) за период "
            f"{result['period_from']} — {result['period_till']} "
            f"(даты закрытия реестра: {dates})."
        )
    else:
        period_label = (
            f"Q{fiscal_quarter} {fiscal_year}"
            if period_type == "quarterly"
            else str(fiscal_year)
        )
        note = (
            f"Дивиденды с датой закрытия реестра в {period_label} не найдены. "
            "Если дивиденды выплачивались, введите вручную."
        )

    return MoexDividendsResponse(
        ticker=result["ticker"],
        fiscal_year=fiscal_year,
        period_type=period_type,
        fiscal_quarter=fiscal_quarter,
        period_from=result["period_from"],
        period_till=result["period_till"],
        total=result["total"],
        currency=result["currency"],
        payments=[DividendPayment(**p) for p in result["payments"]],
        payments_count=len(result["payments"]),
        note=note,
    )


class MoexPriceResponse(BaseModel):
    ticker: str
    requested_date: str
    actual_date: str
    price: float
    board: str
    is_adjusted: bool   # True если фактическая дата отличается от запрошенной
    # Символ, под которым бумага торговалась в тот день, если он отличается
    # от нынешнего: цена за 2022 год у Яндекса лежит под YNDX, а не YDEX.
    resolved_from: Optional[str] = None
    # Если после этой даты был сплит — цена в другом масштабе, чем сегодняшняя.
    split_note: Optional[str] = None



def _price_not_found_detail(lookup: str, requested: str, target_date: date_type) -> str:
    """
    Объясняет пустую котировку вместо «проверьте тикер».

    Две разные причины требуют разных действий: если бумага вышла на биржу
    позже отчёта, цены не существует и вносить туда нечего; если раньше —
    скорее всего сменился символ, и нужна цепочка прежних тикеров.
    """
    prefix = f"Цена для '{lookup}'"
    if lookup != requested:
        prefix += f" (прежний тикер для {requested})"
    prefix += f" на {target_date.isoformat()} не найдена."

    first_trade = get_first_trade_date(lookup)
    if first_trade is None:
        return (
            f"{prefix} Бумага с таким тикером на Мосбирже не торгуется — "
            f"проверьте символ."
        )
    if first_trade > target_date.isoformat():
        return (
            f"{prefix} Первая сделка по бумаге — {first_trade}, то есть отчёт "
            f"старше выхода на биржу: рыночной цены за этот период не существует. "
            f"Если компания торговалась под другим символом, добавьте его "
            f"в «Прежние тикеры» карточки компании."
        )
    return (
        f"{prefix} Торги идут с {first_trade}, но на эту дату сделок нет — "
        f"возможно, бумага была приостановлена. Увеличьте окно поиска."
    )

@router.get(
    "/price/moex",
    response_model=MoexPriceResponse,
    summary="Цена закрытия акции на Мосбирже",
    description=(
        "Возвращает цену закрытия акции на запрошенную дату. "
        "Если в этот день биржа была закрыта (выходной, праздник), "
        "возвращается цена последнего доступного торгового дня."
    ),
)
def get_moex_price(
    ticker: str = Query(..., description="Тикер (SECID) на Мосбирже, например: SBER, GAZP"),
    date: str = Query(..., description="Дата в формате YYYY-MM-DD"),
    company_id: Optional[int] = Query(
        None,
        description=(
            "ID компании. Если передан, тикер подменяется на действовавший "
            "в запрошенную дату — иначе после переименования (YNDX → YDEX) "
            "исторические цены не находятся."
        ),
    ),
    lookback_days: int = Query(
        10,
        ge=1,
        le=30,
        description="Максимум дней назад для поиска последней торговой сессии",
    ),
    db: Session = Depends(get_db),
):
    # Парсинг даты
    try:
        target_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неверный формат даты: '{date}'. Используйте YYYY-MM-DD.",
        )

    requested = ticker.upper()
    lookup = requested
    company = None
    if company_id is not None:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company is not None:
            lookup = resolve_ticker(
                str(company.ticker), company.former_tickers, target_date
            ).upper()

    result = get_closing_price_on_or_before(
        ticker=lookup,
        target_date=target_date,
        lookback_days=lookback_days,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_price_not_found_detail(lookup, requested, target_date),
        )

    return MoexPriceResponse(
        ticker=result["ticker"],
        requested_date=date,
        actual_date=result["date"],
        price=result["price"],
        board=result["board"],
        is_adjusted=result["date"] != date,
        resolved_from=lookup if lookup != requested else None,
        split_note=price_scale_hint(
            company.share_splits if company_id is not None and company else None,
            target_date,
        ),
    )


# ─── Курс валют (MOEX + ЦБ РФ fallback) ──────────────────────────────────────

class FxRateResponse(BaseModel):
    currency: str
    requested_date: str
    actual_date: str
    rate: float
    source: str         # "MOEX" | "CBR"
    is_adjusted: bool   # True если actual_date != requested_date


@router.get(
    "/fx/rate",
    response_model=FxRateResponse,
    summary="Курс иностранной валюты к рублю на дату",
    description=(
        "Возвращает курс валюты (USD/EUR/CNY/…) к рублю на указанную дату.\n\n"
        "Источники в порядке приоритета: "
        "**MOEX** (биржевой курс, WAPRICE) → **ЦБ РФ** (официальный курс).\n\n"
        "Если запрошенная дата — нерабочий день или MOEX прекратил торги "
        "этой валютой (например, USD/EUR после июня 2024), возвращается курс "
        "последнего доступного дня."
    ),
)
def get_fx_rate(
    currency: str = Query(..., description="Код валюты: USD, EUR, CNY, GBP, JPY, CHF"),
    date: str = Query(..., description="Дата в формате YYYY-MM-DD"),
    lookback_days: int = Query(
        10, ge=1, le=30,
        description="Сколько дней искать назад при отсутствии данных на запрошенную дату",
    ),
):
    try:
        target = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неверный формат даты: '{date}'. Используйте YYYY-MM-DD.",
        )

    result = get_fx_rate_on_or_before(
        currency=currency.upper(),
        target_date=target,
        lookback_days=lookback_days,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Курс {currency.upper()}/RUB на {date} не найден. "
                f"Проверьте код валюты или увеличьте lookback_days."
            ),
        )

    return FxRateResponse(
        currency=result["currency"],
        requested_date=date,
        actual_date=result["date"],
        rate=result["rate"],
        source=result["source"],
        is_adjusted=result["date"] != date,
    )


# ─── Бэкфилл исторических цен ─────────────────────────────────────────────────

class BackfillResult(BaseModel):
    company_id: int
    ticker: str
    added: int
    from_date: Optional[str]
    till_date: str


@router.post(
    "/prices/backfill",
    response_model=BackfillResult,
    summary="Ручной бэкфилл цен для одной компании",
    description=(
        "Докачивает пропущенные дневные цены из MOEX для указанной компании. "
        "Используйте после добавления новой компании или если сервер был выключен."
    ),
)
def manual_backfill(
    company_id: int = Query(..., description="ID компании"),
    from_date: Optional[str] = Query(
        None,
        description="Начало диапазона YYYY-MM-DD. Если не указано — автоматически с даты первого отчёта.",
    ),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Компания с id={company_id} не найдена")

    force_from = None
    if from_date:
        try:
            force_from = date_type.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Неверный формат from_date: '{from_date}'. Используйте YYYY-MM-DD.",
            )

    from datetime import date as d_type, timedelta
    till = (d_type.today() - timedelta(days=1)).isoformat()

    added = backfill_company_prices(db, company, force_from=force_from)

    return BackfillResult(
        company_id=company.id,
        ticker=company.ticker,
        added=added,
        from_date=from_date,
        till_date=till,
    )


class BackfillAllResult(BaseModel):
    total_added: int
    by_ticker: dict


@router.post(
    "/prices/backfill-all",
    response_model=BackfillAllResult,
    summary="Бэкфилл цен для всех компаний",
    description="Докачивает пропущенные дневные цены из MOEX для всех компаний в базе.",
)
def manual_backfill_all(db: Session = Depends(get_db)):
    result = backfill_all_companies(db)
    return BackfillAllResult(
        total_added=sum(result.values()),
        by_ticker=result,
    )
