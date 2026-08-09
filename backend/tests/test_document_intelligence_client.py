import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.exceptions import AzureServiceError
from app.integrations.document_intelligence import client as di_client_module
from app.integrations.document_intelligence.client import DocumentIntelligenceAnalyzer


class FakeAzureHttpError(Exception):
    """Stands in for an azure-core `HttpResponseError`-like exception carrying a
    `status_code`, which is all `_once()`'s except-block inspects."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"fake azure error {status_code}")
        self.status_code = status_code


class FakeResult:
    def as_dict(self) -> dict[str, Any]:
        return {"pages": []}


class FakePoller:
    details = {"result_id": "result-123"}

    async def result(self) -> FakeResult:
        return FakeResult()


class FakeTimeoutError(Exception):
    """Stands in for azure-core's `ServiceRequestTimeoutError`/`ServiceResponseTimeoutError`
    - real transport-level timeouts, which (verified against the installed SDK) carry
    no `status_code` attribute at all, unlike an `HttpResponseError`."""


class FlakyDocumentIntelligenceClient:
    """Raises a fake failure on every call up to `fail_times`, then succeeds - used to
    exercise the retry predicate for permanent (4xx), transient (5xx), and transport-
    level (no status_code, e.g. a timeout) failures. `status_code=None` raises
    `FakeTimeoutError` instead of `FakeAzureHttpError` to simulate the latter."""

    def __init__(self, status_code: int | None, fail_times: int) -> None:
        self.status_code = status_code
        self.fail_times = fail_times
        self.calls = 0

    def _raise(self) -> None:
        if self.status_code is None:
            raise FakeTimeoutError("simulated timeout")
        raise FakeAzureHttpError(self.status_code)

    async def begin_analyze_document(self, model_id: str, **_: Any) -> FakePoller:
        self.calls += 1
        if self.calls <= self.fail_times:
            self._raise()
        return FakePoller()

    async def begin_classify_document(self, classifier_id: str, **_: Any) -> FakePoller:
        self.calls += 1
        if self.calls <= self.fail_times:
            self._raise()
        return FakePoller()

    async def delete_analyze_result(self, model_id: str, result_id: str) -> None:
        pass


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
    # The cleanup delete is fire-and-forget (doesn't hold up the caller's
    # concurrency slot) - give the scheduled task a turn to run before asserting.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

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


@pytest.mark.asyncio
async def test_analyze_does_not_retry_permanent_failure(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FlakyDocumentIntelligenceClient(status_code=400, fail_times=999)
    analyzer._client = client  # type: ignore[assignment]

    with pytest.raises(AzureServiceError):
        await analyzer.analyze(source)

    assert client.calls == 1


@pytest.mark.asyncio
async def test_analyze_retries_transient_failure_until_success(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FlakyDocumentIntelligenceClient(status_code=503, fail_times=2)
    analyzer._client = client  # type: ignore[assignment]

    result = await analyzer.analyze(source)

    assert result == {"pages": []}
    assert client.calls == 3


@pytest.mark.asyncio
async def test_classify_does_not_retry_permanent_failure(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FlakyDocumentIntelligenceClient(status_code=403, fail_times=999)
    analyzer._client = client  # type: ignore[assignment]

    with pytest.raises(AzureServiceError):
        await analyzer.classify(source, classifier_id="financial-pages", split_mode="perPage")

    assert client.calls == 1


@pytest.mark.asyncio
async def test_classify_retries_transient_failure_until_success(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FlakyDocumentIntelligenceClient(status_code=503, fail_times=2)
    analyzer._client = client  # type: ignore[assignment]

    result = await analyzer.classify(source, classifier_id="financial-pages", split_mode="perPage")

    assert result == {"pages": []}
    assert client.calls == 3


@pytest.mark.asyncio
async def test_analyze_retries_a_transport_level_timeout(tmp_path: Path) -> None:
    """A real timeout (ServiceRequestTimeoutError et al) carries no status_code at
    all - distinct from an HTTP error response. It must still be retried, not treated
    as a permanent failure just because status_code is missing."""
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FlakyDocumentIntelligenceClient(status_code=None, fail_times=2)
    analyzer._client = client  # type: ignore[assignment]

    result = await analyzer.analyze(source)

    assert result == {"pages": []}
    assert client.calls == 3


@pytest.mark.asyncio
async def test_classify_retries_a_transport_level_timeout(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.pdf"
    source.write_bytes(b"%PDF-synthetic")
    analyzer = DocumentIntelligenceAnalyzer(make_settings(tmp_path))
    client = FlakyDocumentIntelligenceClient(status_code=None, fail_times=2)
    analyzer._client = client  # type: ignore[assignment]

    result = await analyzer.classify(source, classifier_id="financial-pages", split_mode="perPage")

    assert result == {"pages": []}
    assert client.calls == 3


@pytest.mark.asyncio
async def test_client_construction_passes_explicit_timeouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_kwargs: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(di_client_module, "DocumentIntelligenceClient", RecordingClient)
    settings = make_settings(tmp_path)
    analyzer = DocumentIntelligenceAnalyzer(settings)

    await analyzer._get_client()

    assert captured_kwargs["connection_timeout"] == settings.azure_request_timeout_seconds
    assert captured_kwargs["read_timeout"] == settings.azure_request_timeout_seconds


@pytest.mark.asyncio
async def test_client_construction_passes_explicit_timeouts_under_managed_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `api_key` branch is covered above; this app isn't deployed with managed
    identity today, but if it ever is, that branch must get the same timeout
    protection - not silently skip it because it's a separate code path."""
    captured_kwargs: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(di_client_module, "DocumentIntelligenceClient", RecordingClient)
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        storage_root=tmp_path / "storage",
        azure_document_intelligence_endpoint="https://example.test",
        azure_document_intelligence_model_id="prebuilt-layout",
        azure_auth_mode="managed_identity",
    )
    analyzer = DocumentIntelligenceAnalyzer(settings)

    await analyzer._get_client()

    assert captured_kwargs["connection_timeout"] == settings.azure_request_timeout_seconds
    assert captured_kwargs["read_timeout"] == settings.azure_request_timeout_seconds
    # Confirms this actually exercised the managed_identity branch, not api_key.
    assert "credential" in captured_kwargs
    assert type(captured_kwargs["credential"]).__name__ == "DefaultAzureCredential"
