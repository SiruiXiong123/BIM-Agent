"""Tests for bounded model-request retries and backoff behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import BadRequestError

from src.ai.openai_compatible_client import OpenAICompatibleJSONClient


ALB_400_HTML = """<html>
<head><title>400 Bad Request</title></head>
<body><center><h1>400 Bad Request</h1></center><hr><center>alb</center></body>
</html>"""


class SequencedCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(
    outcomes: list[Any],
    *,
    max_request_retries: int = 3,
) -> tuple[OpenAICompatibleJSONClient, SequencedCompletions, list[float]]:
    delays: list[float] = []
    client = OpenAICompatibleJSONClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model_name="test-model",
        json_attempts=1,
        max_request_retries=max_request_retries,
        retry_base_delay_seconds=0.5,
        sleeper=delays.append,
    )
    completions = SequencedCompletions(outcomes)
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=completions)
    )
    return client, completions, delays


def success_response(content: str = '{"ok": true}') -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def bad_request(body: str, *, content_type: str) -> BadRequestError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        text=body,
        headers={"content-type": content_type},
    )
    return BadRequestError("bad request", response=response, body=body)


def test_alb_html_400_retries_three_times_with_exponential_backoff() -> None:
    client, completions, delays = make_client(
        [
            bad_request(ALB_400_HTML, content_type="text/html"),
            bad_request(ALB_400_HTML, content_type="text/html"),
            bad_request(ALB_400_HTML, content_type="text/html"),
            success_response(),
        ]
    )

    result = client.complete_json(system_prompt="test", payload={})

    assert result == {"ok": True}
    assert completions.calls == 4
    assert delays == [0.5, 1.0, 2.0]


def test_alb_html_400_stops_after_three_retries() -> None:
    errors = [
        bad_request(ALB_400_HTML, content_type="text/html")
        for _ in range(4)
    ]
    client, completions, delays = make_client(errors)

    with pytest.raises(BadRequestError):
        client.complete_json(system_prompt="test", payload={})

    assert completions.calls == 4
    assert delays == [0.5, 1.0, 2.0]


def test_structured_invalid_request_400_is_not_retried() -> None:
    error = bad_request(
        '{"error":{"type":"invalid_request_error"}}',
        content_type="application/json",
    )
    client, completions, delays = make_client([error])

    with pytest.raises(BadRequestError):
        client.complete_json(system_prompt="test", payload={})

    assert completions.calls == 1
    assert delays == []


def test_empty_response_retries_with_exponential_backoff_then_succeeds() -> None:
    client, completions, delays = make_client(
        [
            success_response(content=""),
            success_response(),
        ],
        max_request_retries=3,
    )

    result = client.complete_json(system_prompt="test", payload={})

    assert result == {"ok": True}
    assert completions.calls == 2
    assert delays == [0.5]


def test_empty_response_stops_after_retry_limit() -> None:
    client, completions, delays = make_client(
        [
            success_response(content=""),
            success_response(content=""),
            success_response(content=""),
        ],
        max_request_retries=2,
    )

    with pytest.raises(ValueError, match="empty response"):
        client.complete_json(system_prompt="test", payload={})

    assert completions.calls == 3
    assert delays == [0.5, 1.0]


def test_can_disable_provider_thinking_mode() -> None:
    client = OpenAICompatibleJSONClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model_name="test-model",
        enable_thinking=False,
        json_attempts=1,
    )
    completions = SequencedCompletions([success_response()])
    client._client = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=completions)
    )

    result = client.complete_json(system_prompt="test", payload={})

    assert result == {"ok": True}
    assert completions.requests == [
        {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "test"},
                {"role": "user", "content": "{}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 8192,
            "extra_body": {"enable_thinking": False},
        }
    ]


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_rejects_invalid_retry_count(value: Any) -> None:
    with pytest.raises(ValueError, match="max_request_retries"):
        OpenAICompatibleJSONClient(
            base_url="https://example.test/v1",
            api_key="test-key",
            model_name="test-model",
            max_request_retries=value,
        )
