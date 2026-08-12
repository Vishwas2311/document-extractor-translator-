"""PII detector interface: regex detection, Azure adapter fail-closed behavior."""

import pytest

from app.core.exceptions import PolicyBlockedError
from app.services.pii import (
    AzureLanguagePiiDetector,
    RegexPiiDetector,
    build_pii_detector,
)
from app.services.pii.base import PiiSpan, dedupe_overlaps


async def test_regex_detector_finds_structured_pii() -> None:
    detector = RegexPiiDetector()
    results = await detector.detect_batch(
        ["Email case@example.com and call 5551234567"], language="en"
    )
    assert len(results) == 1
    categories = {span.category for span in results[0]}
    assert "email" in categories


async def test_regex_detector_preserves_order_and_length() -> None:
    detector = RegexPiiDetector()
    results = await detector.detect_batch(["no pii here", "id 123456"], language="en")
    assert len(results) == 2
    assert results[0] == []
    assert results[1]  # the second has a numeric id


def test_dedupe_overlaps_keeps_non_overlapping() -> None:
    spans = [
        PiiSpan(0, 5, "a"),
        PiiSpan(3, 8, "b"),  # overlaps first
        PiiSpan(8, 10, "c"),
    ]
    kept = dedupe_overlaps(spans)
    assert [(s.start, s.end) for s in kept] == [(0, 5), (8, 10)]


async def test_azure_detector_fails_closed_without_endpoint() -> None:
    detector = AzureLanguagePiiDetector(endpoint=None)
    with pytest.raises(PolicyBlockedError, match="Failing closed"):
        await detector.detect_batch(["some text"], language="ar")


async def test_azure_detector_fails_closed_on_recognizer_error() -> None:
    async def boom(_documents: list[dict[str, str]]) -> list[list[PiiSpan]]:
        raise RuntimeError("network down")

    detector = AzureLanguagePiiDetector(endpoint="https://x", recognizer=boom)
    with pytest.raises(PolicyBlockedError, match="Failing closed"):
        await detector.detect_batch(["text"], language="zh")


async def test_azure_detector_maps_recognizer_spans() -> None:
    async def fake(documents: list[dict[str, str]]) -> list[list[PiiSpan]]:
        return [[PiiSpan(0, 4, "Person")] for _ in documents]

    detector = AzureLanguagePiiDetector(endpoint="https://x", recognizer=fake)
    results = await detector.detect_batch(["Ali went home"], language="ar")
    assert results == [[PiiSpan(0, 4, "Person")]]


async def test_azure_detector_rejects_incomplete_results() -> None:
    async def short(_documents: list[dict[str, str]]) -> list[list[PiiSpan]]:
        return []  # fewer than inputs

    detector = AzureLanguagePiiDetector(endpoint="https://x", recognizer=short)
    with pytest.raises(PolicyBlockedError, match="incomplete"):
        await detector.detect_batch(["a", "b"], language="en")


def test_build_detector_selects_by_mode() -> None:
    from app.core.config import Settings

    regex = build_pii_detector(Settings(auth_required=False, pii_detection_mode="regex"))
    assert isinstance(regex, RegexPiiDetector)

    multilingual = build_pii_detector(
        Settings(
            auth_required=False,
            pii_detection_mode="multilingual",
            azure_language_endpoint="https://x",
            azure_language_api_key="k",
        )
    )
    assert isinstance(multilingual, AzureLanguagePiiDetector)
