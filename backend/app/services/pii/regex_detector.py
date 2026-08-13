"""Regex-based structured-PII detector for synthetic/development use."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.pii.base import PiiSpan, dedupe_overlaps
from app.services.pii.patterns import ORDERED_PATTERNS


class RegexPiiDetector:
    name = "regex"

    async def detect_batch(
        self, texts: Sequence[str], *, language: str | None = None
    ) -> list[list[PiiSpan]]:
        return [self._detect(text) for text in texts]

    @staticmethod
    def _detect(text: str) -> list[PiiSpan]:
        candidates: list[PiiSpan] = []
        for category, pattern in ORDERED_PATTERNS:
            for match in pattern.finditer(text):
                candidates.append(
                    PiiSpan(start=match.start(), end=match.end(), category=category)
                )
        return dedupe_overlaps(candidates)
