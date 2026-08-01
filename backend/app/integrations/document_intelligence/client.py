from pathlib import Path
from typing import Any

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from app.core.config import Settings
from app.core.exceptions import AzureServiceError, ConfigurationError


class DocumentIntelligenceAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: DocumentIntelligenceClient | None = None

    async def _get_client(self) -> DocumentIntelligenceClient:
        endpoint = self.settings.azure_document_intelligence_endpoint
        api_key = self.settings.azure_document_intelligence_api_key
        if not endpoint or not api_key:
            raise ConfigurationError(
                "Azure Document Intelligence is not configured. Add the endpoint and key."
            )
        if self._client is None:
            self._client = DocumentIntelligenceClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(api_key),
            )
        return self._client

    async def analyze(self, source_path: Path) -> dict[str, Any]:
        client = await self._get_client()
        try:
            from azure.ai.documentintelligence.models import DocumentAnalysisFeature

            with source_path.open("rb") as source:
                poller = await client.begin_analyze_document(
                    self.settings.azure_document_intelligence_model_id,
                    body=source,
                    features=[DocumentAnalysisFeature.LANGUAGES],
                )
                result = await poller.result()
            return result.as_dict()
        except ConfigurationError:
            raise
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            retryable = status_code in {408, 429, 500, 502, 503, 504}
            raise AzureServiceError(
                "Azure Document Intelligence analysis failed.",
                retryable=retryable,
                details={"service": "document_intelligence"},
            ) from exc

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
