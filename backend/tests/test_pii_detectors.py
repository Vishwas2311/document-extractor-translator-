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


async def test_regex_detector_covers_email_nested_in_url() -> None:
    # Regression: URL_RE matches the whole URL (starting before the nested
    # email), while EMAIL_RE independently matches the embedded address. The
    # old start-position-only dedupe kept the url span (it starts earlier)
    # and dropped the email span outright, but the discarded span's tail
    # extended past the kept span - so its non-covered characters stayed in
    # cleartext. Every character either pattern flagged must be masked.
    # Confirmed by code review on 2026-08-12.
    text = "See http://example.com?contact=jane@example.com for details"
    detector = RegexPiiDetector()
    [spans] = await detector.detect_batch([text], language="en")
    email_start = text.index("jane@example.com")
    email_end = email_start + len("jane@example.com")
    assert any(span.start <= email_start and span.end >= email_end for span in spans), (
        f"no span in {spans} fully covers the nested email at [{email_start}, {email_end})"
    )


def test_dedupe_overlaps_keeps_non_overlapping() -> None:
    spans = [
        PiiSpan(0, 5, "a"),
        PiiSpan(6, 8, "b"),
        PiiSpan(8, 10, "c"),
    ]
    kept = dedupe_overlaps(spans)
    assert [(s.start, s.end) for s in kept] == [(0, 5), (6, 8), (8, 10)]


def test_dedupe_overlaps_merges_overlapping_spans_instead_of_dropping_one() -> None:
    # Regression: the previous implementation picked one overlapping span and
    # discarded the other outright, leaving the discarded span's non-covered
    # characters unmasked - e.g. an email nested inside a matched URL, or (as
    # here) a longer id-like match whose tail extends past a shorter one.
    # Confirmed by code review on 2026-08-12.
    spans = [
        PiiSpan(0, 5, "a"),
        PiiSpan(3, 8, "b"),  # overlaps "a" and extends past it
        PiiSpan(8, 10, "c"),
    ]
    kept = dedupe_overlaps(spans)
    # The merged span must cover every character either overlapping span
    # flagged (0-8), not just the earlier-starting one's original range (0-5).
    assert [(s.start, s.end) for s in kept] == [(0, 8), (8, 10)]
    assert kept[0].category == "a"  # earlier (higher-priority) category wins the label


def test_dedupe_overlaps_nested_span_is_fully_covered() -> None:
    # Regression: an email fully nested inside a matched URL must still result
    # in the whole URL being masked, not just the email's inner range.
    spans = [
        PiiSpan(4, 40, "url"),
        PiiSpan(20, 37, "email"),  # nested inside the url span
    ]
    kept = dedupe_overlaps(spans)
    assert [(s.start, s.end) for s in kept] == [(4, 40)]
    assert kept[0].category == "url"


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
