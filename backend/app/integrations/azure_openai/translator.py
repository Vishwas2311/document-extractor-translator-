from typing import Any, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.config import Settings
from app.core.exceptions import AzureServiceError, ConfigurationError
from app.prompts.translation import TRANSLATION_DEVELOPER_PROMPT
from app.schemas.translation import TranslationBatchRequest, TranslationBatchResponse
from app.services.cost_governor import CostGovernor

_FALLBACK_WAIT = wait_random_exponential(multiplier=1, max=20)
_MAX_RATE_LIMIT_WAIT_SECONDS = 60.0
# Rough token estimate for budget accounting only (never for billing): ~4 chars/token.
_CHARS_PER_TOKEN = 4
_PROMPT_TOKEN_OVERHEAD = 256


def estimate_translation_tokens(request: TranslationBatchRequest) -> int:
    payload_chars = len(request.model_dump_json())
    return _PROMPT_TOKEN_OVERHEAD + payload_chars // _CHARS_PER_TOKEN


def translation_retry_wait(retry_state: RetryCallState) -> float:
    """Honor Azure's own `Retry-After` header on a 429 instead of guessing with blind
    backoff. Retrying before Azure's advertised cooldown just spends an attempt to get
    rate-limited again, so a real header value takes priority; anything else (or a
    missing/unparseable header) falls back to the existing random exponential wait."""
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exception, RateLimitError):
        retry_after = exception.response.headers.get("retry-after")
        if retry_after is not None:
            try:
                return min(float(retry_after), _MAX_RATE_LIMIT_WAIT_SECONDS)
            except ValueError:
                pass
    return _FALLBACK_WAIT(retry_state)


class AzureOpenAITranslator:
    def __init__(self, settings: Settings, governor: CostGovernor | None = None) -> None:
        self.settings = settings
        self._client: AsyncOpenAI | None = None
        self._credential: Any | None = None
        self._governor = governor or CostGovernor.from_settings(settings)

    def _get_client(self) -> AsyncOpenAI:
        if self.settings.azure_auth_mode == "managed_identity":
            base_url = self.settings.azure_openai_base_url
            if not base_url or not self.settings.azure_openai_deployment:
                raise ConfigurationError(
                    "Azure OpenAI managed identity requires the base URL and deployment."
                )
            if self._client is None:
                from azure.identity.aio import DefaultAzureCredential

                credential = DefaultAzureCredential()
                self._credential = credential

                async def token_provider() -> str:
                    token = await credential.get_token(
                        "https://cognitiveservices.azure.com/.default"
                    )
                    return str(token.token)

                self._client = AsyncOpenAI(
                    api_key=token_provider,
                    base_url=base_url,
                    timeout=self.settings.azure_request_timeout_seconds,
                    max_retries=0,
                )
            return self._client
        base_url = self.settings.azure_openai_base_url
        api_key = self.settings.azure_openai_api_key
        if not base_url or not api_key or not self.settings.azure_openai_deployment:
            raise ConfigurationError(
                "Azure OpenAI is not configured. Add the v1 base URL, key, "
                "and GPT-5 mini deployment."
            )
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self.settings.azure_request_timeout_seconds,
                max_retries=0,
            )
        return self._client

    async def translate(self, request: TranslationBatchRequest) -> TranslationBatchResponse:
        # Fail closed before doing any billable work if a global budget or the
        # operator kill switch would be exceeded.
        await self._governor.reserve(estimated_tokens=estimate_translation_tokens(request))
        client = self._get_client()
        deployment = self.settings.azure_openai_deployment
        if deployment is None:
            raise ConfigurationError("Azure OpenAI deployment is not configured.")
        retry_types = (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            InternalServerError,
        )
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.settings.azure_max_retries),
                wait=translation_retry_wait,
                retry=retry_if_exception_type(retry_types),
                reraise=True,
            ):
                with attempt:
                    completion = await client.beta.chat.completions.parse(
                        model=deployment,
                        messages=[
                            {"role": "developer", "content": TRANSLATION_DEVELOPER_PROMPT},
                            {"role": "user", "content": request.model_dump_json()},
                        ],
                        response_format=TranslationBatchResponse,
                        reasoning_effort=cast(Any, self.settings.azure_openai_reasoning_effort),
                        max_completion_tokens=self.settings.azure_openai_max_completion_tokens,
                    )
                    message = completion.choices[0].message
                    if message.refusal:
                        raise AzureServiceError(
                            "Azure OpenAI refused a translation batch.",
                            details={"service": "azure_openai", "reason": "refusal"},
                        )
                    if message.parsed is None:
                        raise AzureServiceError(
                            "Azure OpenAI returned no structured translation.",
                            retryable=True,
                            details={"service": "azure_openai"},
                        )
                    return message.parsed
        except ConfigurationError:
            raise
        except AzureServiceError:
            raise
        except retry_types as exc:
            raise AzureServiceError(
                "Azure OpenAI translation failed after retrying.",
                retryable=True,
                details={"service": "azure_openai"},
            ) from exc
        except Exception as exc:
            raise AzureServiceError(
                "Azure OpenAI translation failed.",
                details={"service": "azure_openai"},
            ) from exc
        raise AzureServiceError("Azure OpenAI translation failed.")

    async def check_connectivity(self) -> dict[str, Any]:
        """Make one minimal, real call to Azure OpenAI to verify networking,
        authentication, and deployment access - the diagnostic a live 403/network
        error otherwise requires guessing at. Never sends or returns document
        content: the probe message is a fixed, trivial string, and only a safe
        status/category is reported back, never the raw exception or response body."""
        try:
            client = self._get_client()
        except ConfigurationError as exc:
            return {
                "reachable": False,
                "http_status": None,
                "error_category": "not_configured",
                "detail": exc.message,
            }
        deployment = self.settings.azure_openai_deployment
        try:
            await client.chat.completions.create(
                model=cast(str, deployment),
                messages=[{"role": "user", "content": "ping"}],
                max_completion_tokens=1,
                reasoning_effort=cast(Any, self.settings.azure_openai_reasoning_effort),
            )
        except (AuthenticationError, PermissionDeniedError) as exc:
            return {
                "reachable": False,
                "http_status": exc.status_code,
                "error_category": "auth",
                "detail": "Azure rejected the request's credentials or permissions.",
            }
        except RateLimitError as exc:
            return {
                "reachable": False,
                "http_status": exc.status_code,
                "error_category": "rate_limited",
                "detail": "Azure OpenAI is rate-limiting this deployment.",
            }
        except NotFoundError as exc:
            return {
                "reachable": False,
                "http_status": exc.status_code,
                "error_category": "not_found",
                "detail": "The configured deployment was not found at this endpoint.",
            }
        except (APIConnectionError, APITimeoutError):
            return {
                "reachable": False,
                "http_status": None,
                "error_category": "network",
                "detail": "Could not reach the configured Azure OpenAI endpoint.",
            }
        except APIStatusError as exc:
            return {
                "reachable": False,
                "http_status": exc.status_code,
                "error_category": "unknown",
                "detail": "Azure OpenAI returned an unexpected error.",
            }
        except Exception:
            return {
                "reachable": False,
                "http_status": None,
                "error_category": "unknown",
                "detail": "An unexpected error occurred while contacting Azure OpenAI.",
            }
        return {"reachable": True, "http_status": 200, "error_category": None, "detail": None}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._credential is not None:
            await self._credential.close()
            self._credential = None
