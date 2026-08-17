"""Pluggable PII detection interface.

A detector maps input text to spans of detected PII. The Security Gateway then
tokenizes those spans before any content reaches a generative provider. Keeping
detection behind this interface lets the synthetic/dev regex detector and the
production multilingual detector share exactly the same fail-closed tokenization.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PiiSpan:
    start: int
    end: int
    category: str


@runtime_checkable
class PiiDetector(Protocol):
    name: str

    async def detect_batch(
        self, texts: Sequence[str], *, language: str | None
    ) -> list[list[PiiSpan]]:
        """Return detected PII spans per input text (same order, same length)."""
        ...


def dedupe_overlaps(spans: Sequence[PiiSpan]) -> list[PiiSpan]:
    """Merge overlapping spans into one covering span per overlapping group.

    Tokenization replaces text ranges, so overlapping spans would corrupt each
    other. Discarding one span of an overlapping pair (rather than merging)
    would leave that span's non-covered characters in cleartext - e.g. an
    email nested inside a matched URL, or a longer phone number starting
    just after a shorter ID match. Merging guarantees every character any
    detector flagged is masked, regardless of which span "wins". Candidates
    arrive in category-priority order (see patterns.ORDERED_PATTERNS), and
    the sort below is stable, so the surviving label for a merged group is
    the highest-priority category among the spans that started it.
    """
    ordered = sorted((s for s in spans if s.end > s.start), key=lambda s: s.start)
    merged: list[PiiSpan] = []
    for span in ordered:
        if merged and span.start < merged[-1].end:
            previous = merged[-1]
            merged[-1] = PiiSpan(
                start=previous.start,
                end=max(previous.end, span.end),
                category=previous.category,
            )
            continue
        merged.append(span)
    return merged
