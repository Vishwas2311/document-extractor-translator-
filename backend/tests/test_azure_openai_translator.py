from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, RateLimitError

from app.integrations.azure_openai.translator import translation_retry_wait


def _rate_limit_error(retry_after: str | None) -> RateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(429, headers=headers, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _fake_retry_state(exception: Exception | None, attempt_number: int = 1) -> Any:
    outcome = SimpleNamespace(exception=lambda: exception) if exception is not None else None
    return SimpleNamespace(outcome=outcome, attempt_number=attempt_number)


def test_translation_retry_wait_honors_retry_after_header() -> None:
    state = _fake_retry_state(_rate_limit_error("7"))

    assert translation_retry_wait(state) == 7.0


def test_translation_retry_wait_caps_an_excessive_retry_after_header() -> None:
    state = _fake_retry_state(_rate_limit_error("600"))

    assert translation_retry_wait(state) == 60.0


def test_translation_retry_wait_falls_back_without_a_header() -> None:
    state = _fake_retry_state(_rate_limit_error(None), attempt_number=1)

    result = translation_retry_wait(state)

    assert 0 <= result <= 20


def test_translation_retry_wait_falls_back_for_non_rate_limit_errors() -> None:
    state = _fake_retry_state(APIConnectionError(request=httpx.Request("POST", "https://example.test")))

    result = translation_retry_wait(state)

    assert 0 <= result <= 20


def test_translation_retry_wait_falls_back_on_unparseable_header() -> None:
    state = _fake_retry_state(_rate_limit_error("not-a-number"))

    result = translation_retry_wait(state)

    assert 0 <= result <= 20


@pytest.mark.asyncio
async def test_translation_retry_wait_ignores_missing_outcome() -> None:
    # tenacity only sets `.outcome` after the first attempt's result is known - a
    # defensive guard, not a real code path, but must not crash.
    state = _fake_retry_state(None)

    result = translation_retry_wait(state)

    assert 0 <= result <= 20
