"""Minimal OpenAI-compatible JSON client for the configured Qwen model."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_MAX_REQUEST_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.5
DEFAULT_CLASSIFICATION_MAX_OUTPUT_TOKENS = 768


class OpenAICompatibleJSONClient:
    """Call an OpenAI-compatible chat endpoint and parse one JSON object."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        timeout: float = 120.0,
        max_output_tokens: int = 8192,
        enable_thinking: bool | None = None,
        json_attempts: int = 2,
        max_request_retries: int = DEFAULT_MAX_REQUEST_RETRIES,
        retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        if (
            isinstance(max_request_retries, bool)
            or not isinstance(max_request_retries, int)
            or max_request_retries < 0
        ):
            raise ValueError("max_request_retries must be a non-negative integer")
        if retry_base_delay_seconds < 0:
            raise ValueError("retry_base_delay_seconds cannot be negative")
        self._model_name = model_name
        self._max_output_tokens = max_output_tokens
        self._enable_thinking = enable_thinking
        self._json_attempts = json_attempts
        self._max_request_retries = max_request_retries
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleep = sleeper or time.sleep
        self._client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            # Retry in one visible layer so the configured maximum is exact.
            max_retries=0,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    def complete_json(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._complete_json(
            system_prompt=system_prompt,
            user_content=json.dumps(payload, ensure_ascii=False),
        )

    def complete_json_multimodal(
        self,
        *,
        system_prompt: str,
        content: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Call the model with interleaved text and original-image evidence."""

        return self._complete_json(
            system_prompt=system_prompt,
            user_content=content,
        )

    def _complete_json(
        self,
        *,
        system_prompt: str,
        user_content: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        empty_response_retries_used = 0
        json_attempts_used = 0
        while json_attempts_used < self._json_attempts:
            response = self._create_completion_with_retry(
                system_prompt=system_prompt,
                user_content=user_content,
            )
            content = response.choices[0].message.content
            if not content:
                last_error = ValueError("The model returned an empty response.")
                if empty_response_retries_used >= self._max_request_retries:
                    break
                delay = self._retry_base_delay_seconds * (
                    2**empty_response_retries_used
                )
                empty_response_retries_used += 1
                LOGGER.warning(
                    "Retrying model request after empty response (%s/%s) in %.2fs",
                    empty_response_retries_used,
                    self._max_request_retries,
                    delay,
                )
                self._sleep(delay)
                continue
            json_attempts_used += 1
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if not isinstance(parsed, dict):
                last_error = ValueError(
                    "The model response is not a JSON object."
                )
                continue
            return parsed
        assert last_error is not None
        raise last_error

    def _create_completion_with_retry(
        self,
        *,
        system_prompt: str,
        user_content: str | list[dict[str, Any]],
    ) -> Any:
        retries_used = 0
        while True:
            try:
                started_at = time.perf_counter()
                request_options: dict[str, Any] = {
                    "model": self._model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "max_tokens": self._max_output_tokens,
                }
                if self._enable_thinking is not None:
                    request_options["extra_body"] = {
                        "enable_thinking": self._enable_thinking
                    }
                response = self._client.chat.completions.create(
                    **request_options,
                )
                elapsed = time.perf_counter() - started_at
                usage = getattr(response, "usage", None)
                print(
                    "[LLM USAGE] "
                    f"model={self._model_name} "
                    f"retries={retries_used} "
                    f"elapsed={elapsed:.2f}s "
                    f"prompt_chars={len(system_prompt)} "
                    f"user_chars={_content_size_chars(user_content)} "
                    f"prompt_tokens={_usage_value(usage, 'prompt_tokens')} "
                    f"completion_tokens={_usage_value(usage, 'completion_tokens')} "
                    f"total_tokens={_usage_value(usage, 'total_tokens')}",
                    flush=True,
                )
                return response
            except Exception as exc:
                if (
                    retries_used >= self._max_request_retries
                    or not _is_retryable_request_error(exc)
                ):
                    raise
                delay = self._retry_base_delay_seconds * (2**retries_used)
                retries_used += 1
                LOGGER.warning(
                    "Retrying model request after %s (%s/%s) in %.2fs",
                    type(exc).__name__,
                    retries_used,
                    self._max_request_retries,
                    delay,
                )
                self._sleep(delay)

    @classmethod
    def from_env(
        cls,
        env_path: str | Path = ".env",
        *,
        model_env_key: str = "evacuation_door_model_name",
        timeout_env_key: str | None = None,
        max_output_tokens_env_key: str | None = None,
        enable_thinking_env_key: str | None = None,
        default_timeout: float = 120.0,
        default_max_output_tokens: int = 8192,
        default_enable_thinking: bool | None = None,
    ) -> "OpenAICompatibleJSONClient":
        load_dotenv(env_path)
        base_url = os.getenv("base_url")
        api_key = os.getenv("api_key")
        model_name = os.getenv(model_env_key)
        timeout = _read_float_env(
            timeout_env_key,
            default=default_timeout,
            min_value=1.0,
        )
        max_output_tokens = _read_int_env(
            max_output_tokens_env_key,
            default=default_max_output_tokens,
            min_value=1,
        )
        enable_thinking = _read_bool_env(
            enable_thinking_env_key,
            default=default_enable_thinking,
        )
        missing = [
            name
            for name, value in (
                ("base_url", base_url),
                ("api_key", api_key),
                (model_env_key, model_name),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing .env settings: {', '.join(missing)}")
        return cls(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
        )


def _content_size_chars(value: str | list[dict[str, Any]]) -> int:
    if isinstance(value, str):
        return len(value)
    return len(json.dumps(value, ensure_ascii=False))


def _usage_value(usage: Any, field: str) -> str:
    if usage is None:
        return "unknown"
    value = getattr(usage, field, None)
    return "unknown" if value is None else str(value)


def _read_int_env(
    env_key: str | None,
    *,
    default: int,
    min_value: int,
) -> int:
    if not env_key:
        return default
    raw_value = os.getenv(env_key)
    if raw_value in (None, ""):
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {env_key} must be an integer."
        ) from exc
    if value < min_value:
        raise ValueError(
            f"Environment variable {env_key} must be >= {min_value}."
        )
    return value


def _read_float_env(
    env_key: str | None,
    *,
    default: float,
    min_value: float,
) -> float:
    if not env_key:
        return default
    raw_value = os.getenv(env_key)
    if raw_value in (None, ""):
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {env_key} must be a number."
        ) from exc
    if value < min_value:
        raise ValueError(
            f"Environment variable {env_key} must be >= {min_value}."
        )
    return value


def _read_bool_env(
    env_key: str | None,
    *,
    default: bool | None,
) -> bool | None:
    if not env_key:
        return default
    raw_value = os.getenv(env_key)
    if raw_value in (None, ""):
        return default
    normalized = raw_value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"Environment variable {env_key} must be a boolean value."
    )


def _is_retryable_request_error(exc: Exception) -> bool:
    """Retry transport failures and transient HTTP responses only."""

    if isinstance(
        exc,
        (APIConnectionError, APITimeoutError, RateLimitError),
    ):
        return True
    if not isinstance(exc, APIStatusError):
        return False
    status_code = exc.status_code
    if status_code in {408, 409, 429} or status_code >= 500:
        return True
    if status_code != 400:
        return False
    response = exc.response
    try:
        response_text = response.text
    except Exception:
        response_text = str(exc)
    return _is_alb_html_response(response_text)


def _is_alb_html_response(value: str) -> bool:
    normalized = str(value or "").strip().casefold()
    return (
        (normalized.startswith("<html") or "<html" in normalized)
        and (
            "<center>alb</center>" in normalized
            or ">alb<" in normalized
        )
    )
