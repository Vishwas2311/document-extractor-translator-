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
    """Keep non-overlapping spans, preferring earlier start then longer length.

    Tokenization replaces text ranges, so overlapping spans would corrupt each
    other. Detectors should already avoid overlaps; this is a defensive backstop.
    """
    ordered = sorted(spans, key=lambda s: (s.start, -(s.end - s.start)))
    selected: list[PiiSpan] = []
    last_end = -1
    for span in ordered:
        if span.start < last_end:
            continue
        if span.end <= span.start:
            continue
        selected.append(span)
        last_end = span.end
    return selected
