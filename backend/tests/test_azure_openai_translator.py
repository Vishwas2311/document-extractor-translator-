from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import (
    APIConnectionError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.integrations.azure_openai.translator import (
    AzureOpenAITranslator,
    translation_retry_wait,
)


def _rate_limit_error(retry_after: str | None) -> RateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx.Response(429, headers=headers, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _status_error(error_cls: type[Exception], status_code: int) -> Exception:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return error_cls("boom", response=response, body=None)  # type: ignore[call-arg]


def _configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "azure_auth_mode": "api_key",
        "azure_openai_base_url": "https://example.test/openai/v1",
        "azure_openai_api_key": "secret",
        "azure_openai_deployment": "gpt-5-mini",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class _FakeCompletions:
    def __init__(self, outcome: Exception | None) -> None:
        self._outcome = outcome

    async def create(self, **kwargs: object) -> SimpleNamespace:
        if self._outcome is not None:
            raise self._outcome
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="pong"))])


class _FakeClient:
    def __init__(self, outcome: Exception | None) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(outcome))


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


def test_get_client_constructs_managed_identity_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        azure_auth_mode="managed_identity",
        azure_openai_base_url="https://example.test/openai/v1",
        azure_openai_deployment="gpt-5-mini",
    )
    translator = AzureOpenAITranslator(settings)

    class Credential:
        async def close(self) -> None:
            pass

    monkeypatch.setattr("azure.identity.aio.DefaultAzureCredential", Credential)
    assert translator._get_client() is not None


def test_get_client_succeeds_with_api_key_mode_configured() -> None:
    settings = Settings(
        azure_auth_mode="api_key",
        azure_openai_base_url="https://example.test/openai/v1",
        azure_openai_api_key="secret",
        azure_openai_deployment="gpt-5-mini",
    )
    translator = AzureOpenAITranslator(settings)

    assert translator._get_client() is not None


def test_get_client_still_rejects_missing_api_key() -> None:
    # Explicitly None, not just omitted - a real .env file on the machine running
    # this test could otherwise supply a key and mask the missing-key case.
    settings = Settings(
        azure_auth_mode="api_key",
        azure_openai_base_url="https://example.test/openai/v1",
        azure_openai_api_key=None,
        azure_openai_deployment="gpt-5-mini",
    )
    translator = AzureOpenAITranslator(settings)

    with pytest.raises(ConfigurationError, match="not configured"):
        translator._get_client()


@pytest.mark.asyncio
async def test_check_connectivity_reports_not_configured() -> None:
    settings = _configured_settings(azure_openai_api_key=None)
    translator = AzureOpenAITranslator(settings)

    result = await translator.check_connectivity()

    assert result == {
        "reachable": False,
        "http_status": None,
        "error_category": "not_configured",
        "detail": result["detail"],
    }
    assert "not configured" in str(result["detail"])


@pytest.mark.asyncio
async def test_check_connectivity_reports_success() -> None:
    translator = AzureOpenAITranslator(_configured_settings())
    translator._client = _FakeClient(None)  # type: ignore[assignment]

    result = await translator.check_connectivity()

    assert result == {
        "reachable": True,
        "http_status": 200,
        "error_category": None,
        "detail": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_cls", "status_code", "expected_category"),
    [
        (AuthenticationError, 401, "auth"),
        (PermissionDeniedError, 403, "auth"),
        (NotFoundError, 404, "not_found"),
    ],
)
async def test_check_connectivity_categorizes_status_errors(
    error_cls: type[Exception], status_code: int, expected_category: str
) -> None:
    translator = AzureOpenAITranslator(_configured_settings())
    translator._client = _FakeClient(  # type: ignore[assignment]
        _status_error(error_cls, status_code)
    )

    result = await translator.check_connectivity()

    assert result["reachable"] is False
    assert result["http_status"] == status_code
    assert result["error_category"] == expected_category


@pytest.mark.asyncio
async def test_check_connectivity_categorizes_rate_limit() -> None:
    translator = AzureOpenAITranslator(_configured_settings())
    translator._client = _FakeClient(_rate_limit_error("5"))  # type: ignore[assignment]

    result = await translator.check_connectivity()

    assert result["reachable"] is False
    assert result["http_status"] == 429
    assert result["error_category"] == "rate_limited"


@pytest.mark.asyncio
async def test_check_connectivity_categorizes_network_failure() -> None:
    translator = AzureOpenAITranslator(_configured_settings())
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    translator._client = _FakeClient(  # type: ignore[assignment]
        APIConnectionError(request=request)
    )

    result = await translator.check_connectivity()

    assert result["reachable"] is False
    assert result["http_status"] is None
    assert result["error_category"] == "network"


@pytest.mark.asyncio
async def test_check_connectivity_never_leaks_the_probe_or_raw_exception() -> None:
    # The reported detail must be a fixed, safe sentence - never the raw exception
    # message/body, and never document content (there is none involved anyway).
    translator = AzureOpenAITranslator(_configured_settings())
    translator._client = _FakeClient(  # type: ignore[assignment]
        _status_error(AuthenticationError, 401)
    )

    result = await translator.check_connectivity()

    assert result["detail"] == "Azure rejected the request's credentials or permissions."
