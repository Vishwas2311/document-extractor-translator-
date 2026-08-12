"""Azure AI Language multilingual PII detector (fail-closed).

Targets Azure AI Language's PII recognition, which covers many languages beyond
what regex can (Arabic, Simplified/Traditional Chinese, Hindi, etc.). This adapter
is the production path for ``PII_DETECTION_MODE=multilingual``.

Fail-closed contract: if the service is not configured, unreachable, or returns an
error, detection raises ``PolicyBlockedError`` so the caller must abort before any
content reaches the generative provider. It never returns "no PII" on failure.

The Azure SDK is imported lazily so the rest of the app runs without the optional
dependency installed. A ``recognizer`` callable can be injected for testing and to
keep the SDK-specific mapping isolated.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from app.core.exceptions import PolicyBlockedError
from app.services.pii.base import PiiSpan

Recognizer = Callable[[list[dict[str, str]]], Awaitable[list[list[PiiSpan]]]]


class AzureLanguagePiiDetector:
    name = "multilingual"

    def __init__(
        self,
        *,
        endpoint: str | None,
        api_key: str | None = None,
        azure_auth_mode: str = "api_key",
        recognizer: Recognizer | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._azure_auth_mode = azure_auth_mode
        self._recognizer = recognizer

    async def detect_batch(
        self, texts: Sequence[str], *, language: str | None = None
    ) -> list[list[PiiSpan]]:
        if not texts:
            return []
        if not self._endpoint:
            raise PolicyBlockedError(
                "Multilingual PII detection is selected but the Azure AI Language "
                "endpoint is not configured. Failing closed.",
                details={"service": "azure_language"},
            )
        recognizer = self._recognizer or self._default_recognizer
        documents = [
            {"id": str(index), "text": text, "language": (language or "en")}
            for index, text in enumerate(texts)
        ]
        try:
            results = await recognizer(documents)
        except PolicyBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - any failure must fail closed
            raise PolicyBlockedError(
                "Multilingual PII detection failed. Failing closed before any "
                "content is sent to the generative provider.",
                details={"service": "azure_language"},
            ) from exc
        if len(results) != len(texts):
            raise PolicyBlockedError(
                "Multilingual PII detection returned an incomplete result. Failing closed.",
                details={"service": "azure_language"},
            )
        return results

    async def _default_recognizer(
        self, documents: list[dict[str, str]]
    ) -> list[list[PiiSpan]]:
        try:
            from azure.ai.textanalytics.aio import (  # type: ignore[import-untyped]
                TextAnalyticsClient,
            )
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise PolicyBlockedError(
                "The Azure AI Language SDK is not installed in this build.",
                details={"service": "azure_language"},
            ) from exc

        credential = self._credential()
        # NOTE: Azure returns entity offsets as UTF-16 code units. For the Latin
        # and CJK text this system handles they align with Python indices; text
        # containing astral-plane characters (rare emoji) would need remapping.
        async with TextAnalyticsClient(self._endpoint, credential) as client:
            response = await client.recognize_pii_entities(documents)
            spans_by_doc: list[list[PiiSpan]] = []
            for document in response:
                if getattr(document, "is_error", False):
                    raise PolicyBlockedError(
                        "Azure AI Language reported an error for a document. Failing closed.",
                        details={"service": "azure_language"},
                    )
                spans_by_doc.append(
                    [
                        PiiSpan(
                            start=entity.offset,
                            end=entity.offset + entity.length,
                            category=str(entity.category),
                        )
                        for entity in document.entities
                    ]
                )
            return spans_by_doc

    def _credential(self) -> object:
        if self._azure_auth_mode == "managed_identity":
            from azure.identity.aio import DefaultAzureCredential

            return DefaultAzureCredential()
        from azure.core.credentials import AzureKeyCredential

        if not self._api_key:
            raise PolicyBlockedError(
                "Azure AI Language API key is not configured. Failing closed.",
                details={"service": "azure_language"},
            )
        return AzureKeyCredential(self._api_key)
