"""OpenAI-совместимый клиент для LLM (OpenAI / Ollama / OpenRouter).

Настройки читаются из `app.config.settings` (LLM_* переменные).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletion
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.services.report_parser.schemas import ExtractedReport

logger = logging.getLogger(__name__)


class LLMTransientError(RuntimeError):
    """Временная ошибка: сеть, таймаут, пустой ответ. Ретраим."""


class LLMParseError(RuntimeError):
    """Нераспарсиваемый / невалидный ответ модели. Не ретраим."""


class LLMNotConfiguredError(RuntimeError):
    """В настройках не задан API-ключ / провайдер LLM."""


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


def _call_with_structured_outputs(
    client: OpenAI,
    *,
    system_prompt: str,
    user_prompt: str,
) -> ExtractedReport:
    """Вызов через OpenAI Structured Outputs — гарантированно вернёт JSON
    соответствующий схеме ExtractedReport."""
    try:
        completion = client.beta.chat.completions.parse(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=ExtractedReport,
        )
    except Exception as exc:
        logger.warning("LLM transient error (structured): %s", exc)
        raise LLMTransientError(str(exc)) from exc

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
) -> ExtractedReport:
    """Fallback для провайдеров без structured outputs (Ollama): json_object + ручной парсинг."""
    try:
        completion: ChatCompletion = client.chat.completions.create(
            model=settings.LLM_MODEL,
            temperature=settings.LLM_TEMPERATURE,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("LLM transient error (json_object): %s", exc)
        raise LLMTransientError(str(exc)) from exc

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


@retry(
    retry=retry_if_exception_type(LLMTransientError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)
def extract_report_via_llm(
    *,
    system_prompt: str,
    user_prompt: str,
) -> ExtractedReport:
    """Отправить промпты в LLM и получить валидный ExtractedReport."""
    client = _build_client()
    if _provider_supports_structured_outputs():
        return _call_with_structured_outputs(
            client, system_prompt=system_prompt, user_prompt=user_prompt
        )
    return _call_with_json_object(
        client, system_prompt=system_prompt, user_prompt=user_prompt
    )
