"""PII detection: pluggable multilingual-capable detectors behind one interface."""

from __future__ import annotations

from app.core.config import Settings
from app.core.exceptions import PolicyBlockedError
from app.services.pii.azure_language import AzureLanguagePiiDetector
from app.services.pii.base import PiiDetector, PiiSpan, dedupe_overlaps
from app.services.pii.regex_detector import RegexPiiDetector

__all__ = [
    "AzureLanguagePiiDetector",
    "PiiDetector",
    "PiiSpan",
    "RegexPiiDetector",
    "build_pii_detector",
    "dedupe_overlaps",
]


def build_pii_detector(settings: Settings) -> PiiDetector:
    """Select the detector for the configured mode, failing closed on anything else."""
    mode = settings.pii_detection_mode
    if mode == "regex":
        return RegexPiiDetector()
    if mode == "multilingual":
        return AzureLanguagePiiDetector(
            endpoint=settings.azure_language_endpoint,
            api_key=settings.azure_language_api_key,
            azure_auth_mode=settings.azure_auth_mode,
        )
    raise PolicyBlockedError(
        "Unsupported PII detection mode. Failing closed.",
        details={"reason": mode},
    )
