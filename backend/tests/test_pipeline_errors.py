"""Перевод ошибок LLM-конвейера в HTTP-коды.

Раньше этот каскад стоял двумя копиями внутри эндпоинтов и не проверялся
ничем: чтобы увидеть 429 с заголовком Retry-After, нужно было получить отказ
от живой модели. Все ошибки конвейера — наследники RuntimeError, поэтому
главное, что здесь проверяется, — порядок: частный тип не должен схлопнуться
в общий 422.
"""
import pytest

from app.routers.pipeline_errors import http_error_for
from app.services.report_parser.extractor_service import (
    ReportAlreadyExistsError,
    ReportNotFoundForComparison,
)
from app.services.report_parser.llm_client import (
    LLMNotConfiguredError,
    LLMParseError,
    LLMRateLimitError,
    LLMTransientError,
)


def _code(exc, **kwargs) -> int:
    return http_error_for(exc, action="Не удалось обработать PDF", **kwargs).status_code


def test_llm_not_configured_is_service_unavailable():
    assert _code(LLMNotConfiguredError("нет ключа")) == 503


def test_bad_json_from_model_is_bad_gateway():
    err = http_error_for(LLMParseError("не JSON"), action="Не удалось обработать PDF")

    assert err.status_code == 502
    assert "некорректный JSON" in err.detail


def test_rate_limit_carries_retry_after_header():
    """429 без Retry-After бесполезен: клиент не знает, когда повторить."""
    exc = LLMRateLimitError("TPM exceeded")
    exc.retry_after = 42

    err = http_error_for(exc, action="Не удалось обработать PDF")

    assert err.status_code == 429
    assert err.headers == {"Retry-After": "42"}
    assert "42" in err.detail


def test_rate_limit_checked_before_transient():
    """LLMRateLimitError — наследник LLMTransientError; порядок проверок важен."""
    exc = LLMRateLimitError("TPM exceeded")
    exc.retry_after = 5

    assert _code(exc) == 429
    assert _code(LLMTransientError("таймаут")) == 504


def test_runtime_error_from_pdf_stage_is_unprocessable():
    """PDF без финансовых страниц — не ошибка сервера, а негодный файл."""
    assert _code(RuntimeError("в PDF не найдено таблиц")) == 422


def test_specific_types_win_over_generic_runtime():
    """Ошибки эндпоинта — наследники RuntimeError и должны проверяться первыми."""
    assert _code(
        ReportAlreadyExistsError("отчёт уже есть"),
        specific={ReportAlreadyExistsError: 409},
    ) == 409
    assert _code(
        ReportNotFoundForComparison("нечего сравнивать"),
        specific={ReportNotFoundForComparison: 404},
    ) == 404


def test_same_error_maps_differently_per_endpoint():
    """Без `specific` тот же тип уходит в общий 422 — это разница эндпоинтов."""
    assert _code(ReportAlreadyExistsError("отчёт уже есть")) == 422


def test_value_error_is_client_mistake_only_where_declared():
    assert _code(ValueError("год в будущем"), specific={ValueError: 400}) == 400
    # Там, где эндпоинт этого не объявил, поведение прежнее — 500.
    assert _code(ValueError("год в будущем")) == 500


def test_unknown_error_becomes_500_with_action_text():
    err = http_error_for(
        OSError("диск отвалился"),
        action="Не удалось сравнить PDF",
        context="company_id=17",
    )

    assert err.status_code == 500
    assert "Не удалось сравнить PDF" in err.detail
