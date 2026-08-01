from typing import Any, cast

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from app.core.config import Settings
from app.core.exceptions import AzureServiceError, ConfigurationError
from app.prompts.translation import TRANSLATION_DEVELOPER_PROMPT
from app.schemas.translation import TranslationBatchRequest, TranslationBatchResponse


class AzureOpenAITranslator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
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
                wait=wait_random_exponential(multiplier=1, max=20),
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

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
