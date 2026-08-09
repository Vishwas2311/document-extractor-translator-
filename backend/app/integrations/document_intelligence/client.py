"""Document Intelligence client with result deletion and feature wiring."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.config import Settings
from app.core.exceptions import AzureServiceError, ConfigurationError

logger = structlog.get_logger(__name__)


def _is_retryable_azure_error(exc: BaseException) -> bool:
    """Only retry transient failures (408/429/5xx) - a 400/401/403 wrapped as
    `AzureServiceError` is permanent and retrying it just delays the inevitable failure
    while burning the Azure quota."""
    return isinstance(exc, AzureServiceError) and getattr(exc, "retryable", False)


def _result_id_from_poller(poller: Any) -> str | None:
    details = getattr(poller, "details", None) or {}
    if isinstance(details, dict):
        for key in ("result_id", "operationId", "operation_id"):
            value = details.get(key)
            if value:
                return str(value)
        location = details.get("operation_location") or details.get("operationLocation")
        if location:
            return Path(urlparse(str(location)).path).name or None
    location = getattr(poller, "continuation_token", None)
    if location:
        return Path(str(location)).name or None
    return None


class DocumentIntelligenceAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: DocumentIntelligenceClient | None = None

    async def _get_client(self) -> DocumentIntelligenceClient:
        endpoint = self.settings.azure_document_intelligence_endpoint
        if not endpoint:
            raise ConfigurationError(
                "Azure Document Intelligence is not configured. Add the endpoint and key."
            )

        if self._client is None:
            mode = self.settings.azure_auth_mode.lower()
            if mode == "managed_identity":
                try:
                    from azure.identity.aio import DefaultAzureCredential
                except ImportError as exc:
                    raise ConfigurationError(
                        "azure-identity is required for managed_identity auth mode."
                    ) from exc
                self._client = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=DefaultAzureCredential(),
                    connection_timeout=self.settings.azure_request_timeout_seconds,
                    read_timeout=self.settings.azure_request_timeout_seconds,
                )
            elif mode == "api_key":
                api_key = self.settings.azure_document_intelligence_api_key
                if not api_key:
                    raise ConfigurationError(
                        "Azure Document Intelligence is not configured. Add the endpoint and key."
                    )
                self._client = DocumentIntelligenceClient(
                    endpoint=endpoint,
                    credential=AzureKeyCredential(api_key),
                    connection_timeout=self.settings.azure_request_timeout_seconds,
                    read_timeout=self.settings.azure_request_timeout_seconds,
                )
            else:
                raise ConfigurationError(
                    f"Unknown AZURE_AUTH_MODE '{self.settings.azure_auth_mode}'. Failing closed."
                )
        return self._client

    def _features(self) -> list[Any]:
        from azure.ai.documentintelligence.models import DocumentAnalysisFeature

        requested = {
            item.strip().lower()
            for item in self.settings.azure_document_intelligence_features.split(",")
            if item.strip()
        }
        features: list[Any] = []
        if "languages" in requested:
            features.append(DocumentAnalysisFeature.LANGUAGES)
        return features

    async def analyze(
        self,
        source_path: Path,
        *,
        pages: str | None = None,
    ) -> dict[str, Any]:
        """Analyze a document, optionally limited to a 1-based page range string.

        `pages` uses Azure DI syntax, e.g. ``"1-25"`` or ``"26-50"``. Passing
        page ranges keeps large PDFs under service timeouts and enables
        progressive extraction.
        """
        client = await self._get_client()

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.settings.azure_max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception(_is_retryable_azure_error),
        )
        async def _once() -> dict[str, Any]:
            try:
                with source_path.open("rb") as source:
                    poller = await client.begin_analyze_document(
                        self.settings.azure_document_intelligence_model_id,
                        body=source,
                        pages=pages,
                        features=self._features() or None,
                    )
                    result = await asyncio.wait_for(
                        poller.result(), timeout=self.settings.azure_operation_max_seconds
                    )
                payload = result.as_dict()
                result_id = _result_id_from_poller(poller)
                if result_id:
                    # Fire-and-forget: this is server-side cleanup, not part of the
                    # result. Awaiting it here would hold the caller's range-analysis
                    # semaphore slot for one extra network round trip per range,
                    # serializing cleanup against the next range's work for no reason.
                    # `_delete_analyze_result` already catches and logs its own
                    # exceptions, so a bare fire-and-forget task cannot leak or crash.
                    asyncio.create_task(
                        self._delete_analyze_result(
                            client,
                            self.settings.azure_document_intelligence_model_id,
                            result_id,
                        )
                    )
                else:
                    await logger.awarning("di_result_id_missing_skip_delete")
                return payload
            except ConfigurationError:
                raise
            except AzureServiceError:
                raise
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                # A transport-level failure (connection refused, DNS, or - critically -
                # a timeout) never reaches the point of getting an HTTP status at all,
                # so `status_code` is None here even though the failure is exactly the
                # kind that's worth retrying. Only an *observed* permanent status
                # (400/401/403/etc, not in the retryable set) should suppress retry.
                retryable = status_code is None or status_code in {408, 429, 500, 502, 503, 504}
                raise AzureServiceError(
                    "Azure Document Intelligence analysis failed.",
                    retryable=retryable,
                ) from exc

        return await _once()

    async def classify(
        self,
        source_path: Path,
        *,
        classifier_id: str,
        split_mode: str,
        pages: str | None = None,
    ) -> dict[str, Any]:
        """Classify source pages with an approved Azure DI custom classifier."""
        if not classifier_id.strip():
            raise ConfigurationError("A Document Intelligence classifier ID is required.")
        client = await self._get_client()

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.settings.azure_max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception(_is_retryable_azure_error),
        )
        async def _once() -> dict[str, Any]:
            try:
                with source_path.open("rb") as source:
                    poller = await client.begin_classify_document(
                        classifier_id,
                        body=source,
                        split=split_mode,
                        pages=pages,
                    )
                    result = await asyncio.wait_for(
                        poller.result(), timeout=self.settings.azure_operation_max_seconds
                    )
                payload = result.as_dict()
                result_id = _result_id_from_poller(poller)
                if result_id:
                    # Classifier results use the documentClassifiers route. The current
                    # SDK/REST surface has no classifier-result deletion operation.
                    await logger.awarning(
                        "di_classifier_result_delete_unsupported",
                        classifier_id=classifier_id,
                        result_id=result_id,
                    )
                else:
                    await logger.awarning("di_classifier_result_id_missing_skip_delete")
                return payload
            except ConfigurationError:
                raise
            except AzureServiceError:
                raise
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                # A transport-level failure (connection refused, DNS, or - critically -
                # a timeout) never reaches the point of getting an HTTP status at all,
                # so `status_code` is None here even though the failure is exactly the
                # kind that's worth retrying. Only an *observed* permanent status
                # (400/401/403/etc, not in the retryable set) should suppress retry.
                retryable = status_code is None or status_code in {408, 429, 500, 502, 503, 504}
                raise AzureServiceError(
                    "Azure Document Intelligence classification failed.",
                    retryable=retryable,
                ) from exc

        return await _once()

    async def _delete_analyze_result(
        self,
        client: DocumentIntelligenceClient,
        model_id: str,
        result_id: str,
    ) -> None:
        try:
            delete = getattr(client, "delete_analyze_result", None)
            if delete is None:
                await logger.awarning("di_delete_analyze_result_unsupported")
                return
            await delete(model_id, result_id)
            await logger.ainfo(
                "di_analyze_result_deleted",
                model_id=model_id,
                result_id=result_id,
            )
        except Exception:
            await logger.aexception("di_analyze_result_delete_failed", result_id=result_id)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
