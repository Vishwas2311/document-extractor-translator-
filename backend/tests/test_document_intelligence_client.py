from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.integrations.document_intelligence.client import DocumentIntelligenceAnalyzer


class FakeResult:
    def as_dict(self) -> dict[str, Any]:
        return {"pages": []}


class FakePoller:
    details = {"result_id": "result-123"}

    async def result(self) -> FakeResult:
        return FakeResult()


class FakeDocumentIntelligenceClient:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.analyzed_model_id: str | None = None
        self.classifier_id: str | None = None

    async def begin_analyze_document(self, model_id: str, **_: Any) -> FakePoller:
        self.analyzed_model_id = model_id
        return FakePoller()

    async def begin_classify_document(self, classifier_id: str, **_: Any) -> FakePoller:
        self.classifier_id = classifier_id
        return FakePoller()

    async def delete_analyze_result(self, model_id: str, result_id: str) -> None:
        self.deleted.append((model_id, result_id))


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        storage_root=tmp_path / "storage",
        azure_document_intelligence_endpoint="https://example.test",
        azure_document_intelligence_api_key="synthetic-test-key",
        azure_document_intelligence_model_id="prebuilt-layout",
    )


@pytest.mark.asyncio
async def test_analyze_deletes_result_with_model_and_result_ids(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FakeDocumentIntelligenceClient()
    analyzer._client = client  # type: ignore[assignment]

    result = await analyzer.analyze(source)

    assert result == {"pages": []}
    assert client.analyzed_model_id == "prebuilt-layout"
    assert client.deleted == [("prebuilt-layout", "result-123")]


@pytest.mark.asyncio
async def test_classifier_does_not_call_document_model_deletion(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FakeDocumentIntelligenceClient()
    analyzer._client = client  # type: ignore[assignment]

    result = await analyzer.classify(
        source,
        classifier_id="financial-pages",
        split_mode="perPage",
    )

    assert result == {"pages": []}
    assert client.classifier_id == "financial-pages"
    assert client.deleted == []
