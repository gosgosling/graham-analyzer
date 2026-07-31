"""Перевод ошибок LLM-конвейера в HTTP-ответы.

Один и тот же каскад `except` (503 → 502 → 429 → 504 → 422 → 500) стоял
подряд в двух эндпоинтах разбора PDF: 31 и 16 строк копии. Копии уже начали
расходиться — в одном месте `ValueError` отдавал 400, в другом уходил в 500.
Теперь правило одно, а специфика эндпоинта передаётся параметром.

Все ошибки конвейера — наследники `RuntimeError`, поэтому порядок проверок
важен: сначала то, что назвал вызывающий, затем частные типы LLM, и только
потом общий `RuntimeError`.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional, Type

from fastapi import HTTPException, status

from app.services.report_parser.llm_client import (
    LLMNotConfiguredError,
    LLMParseError,
    LLMRateLimitError,
    LLMTransientError,
)

logger = logging.getLogger(__name__)


def http_error_for(
    exc: Exception,
    *,
    action: str,
    context: str = "",
    specific: Optional[Mapping[Type[Exception], int]] = None,
) -> HTTPException:
    """Подобрать HTTP-ответ под ошибку конвейера.

    Args:
        exc:      пойманное исключение.
        action:   что не удалось сделать — попадёт в текст 500-й ошибки
                  («Не удалось обработать PDF»).
        context:  что писать в лог рядом с ошибкой (например, company_id=17).
        specific: типы, которые этот эндпоинт трактует по-своему, в порядке
                  проверки: `{ReportAlreadyExistsError: 409}`.

    Returns:
        HTTPException — вызывающий делает `raise ... from exc`, чтобы в логе
        осталась исходная цепочка.
    """
    for exc_type, code in (specific or {}).items():
        if isinstance(exc, exc_type):
            return HTTPException(status_code=code, detail=str(exc))

    if isinstance(exc, LLMNotConfiguredError):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    if isinstance(exc, LLMParseError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM вернул некорректный JSON: {exc}",
        )

    # Проверяется раньше LLMTransientError — это его наследник.
    if isinstance(exc, LLMRateLimitError):
        retry_after = int(exc.retry_after)
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Превышен лимит запросов к LLM (TPM/RPM). "
                f"Подожди ~{retry_after} сек и повтори попытку. "
                f"Оригинал: {exc}"
            ),
            headers={"Retry-After": str(retry_after)},
        )

    if isinstance(exc, LLMTransientError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"LLM временно недоступен: {exc}",
        )

    # extract_financial_pages бросает RuntimeError, если в PDF ничего не нашлось.
    if isinstance(exc, RuntimeError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    logger.exception("%s (%s): %s", action, context or "без контекста", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"{action}: {exc}",
    )
