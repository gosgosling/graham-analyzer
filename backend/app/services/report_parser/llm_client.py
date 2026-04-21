"""OpenAI-совместимый клиент для LLM (OpenAI / Ollama / OpenRouter).

Настройки читаются из `app.config.settings` (LLM_* переменные).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, NoReturn, Optional

from openai import OpenAI, RateLimitError
from openai.types.chat import ChatCompletion
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
)

from app.config import settings
from app.services.report_parser.schemas import ExtractedReport

logger = logging.getLogger(__name__)


class LLMTransientError(RuntimeError):
    """Временная ошибка: сеть, таймаут, пустой ответ. Ретраим."""


class LLMRateLimitError(LLMTransientError):
    """HTTP 429 — TPM/RPM лимит у провайдера. Ретраим с учётом Retry-After."""

    def __init__(self, message: str, retry_after: float = 15.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMParseError(RuntimeError):
    """Нераспарсиваемый / невалидный ответ модели. Не ретраим."""


class LLMNotConfiguredError(RuntimeError):
    """В настройках не задан API-ключ / провайдер LLM."""


def _parse_retry_after(exc: RateLimitError) -> float:
    """Достать, сколько ждать, из RateLimitError:
       1) заголовок Retry-After (секунды);
       2) текст сообщения 'try again in 15.646s';
       3) дефолт 15 сек.
    """
    # (1) заголовки ответа (openai v1 кладёт Response в exc.response)
    try:
        resp = getattr(exc, "response", None)
        if resp is not None and getattr(resp, "headers", None):
            hdr = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
            if hdr:
                try:
                    return max(1.0, float(hdr))
                except ValueError:
                    pass
    except Exception:  # noqa: BLE001
        pass

    # (2) текст сообщения — OpenAI пишет 'Please try again in 15.646s'
    msg = str(exc)
    m = re.search(r"try again in ([\d.]+)s", msg, flags=re.IGNORECASE)
    if m:
        try:
            return max(1.0, float(m.group(1)))
        except ValueError:
            pass
    # 'try again in 500ms'
    m_ms = re.search(r"try again in ([\d.]+)ms", msg, flags=re.IGNORECASE)
    if m_ms:
        try:
            return max(1.0, float(m_ms.group(1)) / 1000.0)
        except ValueError:
            pass

    return 15.0


def _raise_as_transient(exc: Exception, *, context: str) -> NoReturn:
    """Превращает исключения openai-sdk в наши, сохраняя подсказку retry-after."""
    if isinstance(exc, RateLimitError):
        retry_after = _parse_retry_after(exc)
        logger.warning(
            "LLM rate limit (%s): жду %.1f сек до ретрая. %s",
            context, retry_after, exc,
        )
        raise LLMRateLimitError(str(exc), retry_after=retry_after) from exc
    logger.warning("LLM transient error (%s): %s", context, exc)
    raise LLMTransientError(str(exc)) from exc


def _build_client() -> OpenAI:
    if not settings.llm_configured:
        raise LLMNotConfiguredError(
            "LLM не сконфигурирован. Задай LLM_API_KEY (или LLM_BASE_URL "
            "для Ollama) в корневом .env проекта."
        )
    # Для Ollama api_key может быть пустым, но openai SDK требует непустую строку.
    api_key = settings.LLM_API_KEY or "not-needed"
    return OpenAI(
        base_url=settings.LLM_BASE_URL,
        api_key=api_key,
        timeout=settings.LLM_REQUEST_TIMEOUT,
        max_retries=0,
    )


def _extract_json_string(content: str) -> str:
    """Достать тело JSON из ответа модели (снять markdown-ограды если есть)."""
    stripped = content.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("{"):
                return p
            if p.startswith("json"):
                body = p[len("json"):].strip()
                if body.startswith("{"):
                    return body
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _provider_supports_structured_outputs() -> bool:
    """OpenAI и OpenRouter поддерживают `response_format=<pydantic-class>`.
    Ollama — нет (использует json_object)."""
    return settings.LLM_PROVIDER.lower() in {"openai", "openrouter"}


def _build_user_content(
    user_prompt: str, images: Optional[list[bytes]]
) -> Any:
    """Сформировать content для user-сообщения: только текст или text+images.

    Используется для PDF-сканов: pymupdf рендерит страницы в PNG, мы отправляем
    их вместе с текстом — gpt-4o-mini / gpt-4o умеют читать таблицы из картинок.
    """
    if not images:
        return user_prompt

    parts: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for img in images:
        if not img:
            continue
        b64 = base64.b64encode(img).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    # 'auto' — OpenAI сам решит уровень детализации. Для
                    # финансовых таблиц обычно выбирает 'high' (дороже, но
                    # читает мелкие цифры в строках).
                    "detail": "high",
                },
            }
        )
    return parts


def _call_with_structured_outputs(
    client: OpenAI,
    *,
    system_prompt: str,
    user_prompt: str,
    images: Optional[list[bytes]] = None,
) -> ExtractedReport:
    """Вызов через OpenAI Structured Outputs — гарантированно вернёт JSON
    соответствующий схеме ExtractedReport."""
    try:
        completion = client.beta.chat.completions.parse(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_user_content(user_prompt, images)},
            ],
            response_format=ExtractedReport,
        )
    except Exception as exc:
        _raise_as_transient(exc, context="structured")

    if not completion.choices:
        raise LLMTransientError("LLM вернул пустой список choices")
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        refusal = completion.choices[0].message.refusal
        raise LLMParseError(
            f"LLM не вернул parsed-ответ. Refusal: {refusal or 'нет'}"
        )
    return parsed


def _call_with_json_object(
    client: OpenAI,
    *,
    system_prompt: str,
    user_prompt: str,
    images: Optional[list[bytes]] = None,
) -> ExtractedReport:
    """Fallback для провайдеров без structured outputs (Ollama): json_object + ручной парсинг."""
    try:
        completion: ChatCompletion = client.chat.completions.create(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_user_content(user_prompt, images)},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        _raise_as_transient(exc, context="json_object")

    if not completion.choices:
        raise LLMTransientError("LLM вернул пустой список choices")

    content = (completion.choices[0].message.content or "").strip()
    if not content:
        raise LLMTransientError("LLM вернул пустое сообщение")

    json_str = _extract_json_string(content)
    try:
        payload: dict[str, Any] = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("LLM вернул невалидный JSON. Сырой ответ:\n%s", content)
        raise LLMParseError(f"Невалидный JSON: {exc}") from exc

    try:
        return ExtractedReport.model_validate(payload)
    except ValidationError as exc:
        logger.error(
            "LLM JSON не проходит валидацию. Payload:\n%s\nОшибка: %s",
            json.dumps(payload, ensure_ascii=False, indent=2),
            exc,
        )
        raise LLMParseError(f"Ошибка валидации ExtractedReport: {exc}") from exc


def _wait_strategy(retry_state: Any) -> float:
    """Стратегия ожидания между ретраями:
      * для 429 RateLimit — ждём ровно столько, сколько рекомендовал OpenAI
        в заголовке Retry-After (+ небольшой запас на пересчёт TPM-окна);
      * для прочих временных ошибок — экспоненциальный backoff 2..20 сек.
    """
    exc = (
        retry_state.outcome.exception()
        if retry_state.outcome is not None and retry_state.outcome.failed
        else None
    )
    if isinstance(exc, LLMRateLimitError):
        wait_s = exc.retry_after + 2.0  # +2 сек чтобы окно TPM точно сбросилось
        logger.info(
            "Retry-After от провайдера: %.1f сек (попытка %d/5).",
            wait_s, retry_state.attempt_number,
        )
        return wait_s
    # обычный экспоненциальный backoff
    base = min(20.0, 2.0 * (2 ** (retry_state.attempt_number - 1)))
    return max(2.0, base)


@retry(
    retry=retry_if_exception_type(LLMTransientError),
    stop=stop_after_attempt(5),  # больше попыток: TPM-лимит может держаться 1-2 минуты
    wait=_wait_strategy,
    reraise=True,
)
def extract_report_via_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    images: Optional[list[bytes]] = None,
) -> ExtractedReport:
    """Отправить промпты в LLM и получить валидный ExtractedReport.

    Если передан список ``images`` (PNG-байты), они прикрепляются к
    user-сообщению в OpenAI-vision формате. Используется для скан-PDF,
    где текст не извлекается программно и нужно OCR через саму модель
    (gpt-4o / gpt-4o-mini умеют читать таблицы с картинок).
    """
    client = _build_client()
    if _provider_supports_structured_outputs():
        return _call_with_structured_outputs(
            client, system_prompt=system_prompt, user_prompt=user_prompt,
            images=images,
        )
    if images:
        logger.warning(
            "Провайдер %s не поддерживает структурированные outputs — "
            "vision-режим может работать нестабильно.",
            settings.LLM_PROVIDER,
        )
    return _call_with_json_object(
        client, system_prompt=system_prompt, user_prompt=user_prompt,
        images=images,
    )
