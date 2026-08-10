"""Data Security Gateway — profile selection, minimization, and pseudonymization.

Local PRD-ready implementation. Production replaces detectors with multilingual PII
models and Key Vault–backed token maps; the fail-closed contract stays the same.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.enums import DataClass, ProcessingProfile
from app.core.exceptions import PolicyBlockedError
from app.schemas.translation import TranslationInput

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
# Long digit runs and common ID-like tokens (case numbers, MRNs, etc.).
ID_RE = re.compile(r"\b(?:ID|MRN|SSN|NINO|CASE)[-:#\s]?\d{4,}\b|\b\d{6,}\b", re.IGNORECASE)
# Matches a pseudonym token as generated in `_pseudonymize` below (e.g. "⟦ID_a3f9c2d1e4b5⟧").
# Single source of truth for the token shape, reused by validation.py's round-trip
# integrity check so the two can never silently drift apart.
PSEUDONYM_TOKEN_RE = re.compile(r"⟦[A-Z]+_[0-9a-f]{12}⟧")


@dataclass
class PseudonymizationResult:
    inputs: list[TranslationInput]
    token_map: dict[str, str] = field(default_factory=dict)
    detections: int = 0


class SecurityGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        secret = settings.pseudonymization_secret or settings.app_name
        self._secret = secret.encode("utf-8")

    def select_profile(
        self,
        *,
        data_class: str,
        requested_profile: str | None = None,
        trusted_stored: bool = False,
    ) -> ProcessingProfile:
        """Select the effective profile. Client requests cannot escalate to raw LLM."""
        classified = self._parse_data_class(data_class)
        default = self._parse_profile(self.settings.default_processing_profile)

        if requested_profile:
            requested = self._parse_profile(requested_profile)
            # Never allow client to pick a riskier profile than the server default,
            # unless this is the profile already persisted by the server at upload.
            if (
                not trusted_stored
                and self._risk_rank(requested) > self._risk_rank(default)
            ):
                raise PolicyBlockedError(
                    "The client cannot select a higher-risk processing profile than "
                    "the server allows.",
                    details={"requested": requested.value, "allowed": default.value},
                )
            profile = requested
        else:
            profile = default

        if classified in {DataClass.CONFIDENTIAL, DataClass.RESTRICTED}:
            if profile == ProcessingProfile.GENAI_SYNTHETIC_POC:
                raise PolicyBlockedError(
                    "Synthetic-only LLM profile cannot process confidential or restricted data.",
                    details={"data_class": classified.value, "profile": profile.value},
                )
            if profile == ProcessingProfile.GENAI_RAW_EXCEPTION:
                if not self.settings.genai_raw_exception_enabled:
                    raise PolicyBlockedError(
                        "Raw generative LLM exception is not enabled.",
                        details={"data_class": classified.value},
                    )
            elif profile not in {
                ProcessingProfile.GENAI_PSEUDONYMIZED,
                ProcessingProfile.MANAGED_NO_LLM,
                ProcessingProfile.BLOCKED,
            }:
                raise PolicyBlockedError(
                    "No approved processing profile for this data class.",
                    details={"data_class": classified.value, "profile": profile.value},
                )

        if classified == DataClass.SYNTHETIC and profile == ProcessingProfile.GENAI_SYNTHETIC_POC:
            if not self.settings.allow_synthetic_raw_llm:
                raise PolicyBlockedError(
                    "Synthetic raw LLM path is disabled. Use GENAI_PSEUDONYMIZED.",
                    details={"profile": profile.value},
                )

        if profile == ProcessingProfile.BLOCKED:
            raise PolicyBlockedError("Processing is blocked by policy.")

        if profile == ProcessingProfile.MANAGED_NO_LLM:
            raise PolicyBlockedError(
                "MANAGED_NO_LLM is selected; generative translation is not available "
                "in this build.",
                details={"profile": profile.value},
            )

        return profile

    def prepare_translation_inputs(
        self,
        profile: ProcessingProfile,
        inputs: list[TranslationInput],
    ) -> PseudonymizationResult:
        if profile in {
            ProcessingProfile.GENAI_SYNTHETIC_POC,
            ProcessingProfile.GENAI_RAW_EXCEPTION,
        }:
            return PseudonymizationResult(inputs=list(inputs), detections=0)

        if profile != ProcessingProfile.GENAI_PSEUDONYMIZED:
            raise PolicyBlockedError(
                "Unknown or unsupported profile for generative translation.",
                details={"profile": profile.value},
            )

        token_map: dict[str, str] = {}
        prepared: list[TranslationInput] = []
        detections = 0
        for item in inputs:
            text, found = self._pseudonymize(item.source_text, token_map)
            detections += found
            prepared.append(
                TranslationInput(
                    block_id=item.block_id,
                    source_language=item.source_language,
                    source_text=text,
                )
            )
        return PseudonymizationResult(inputs=prepared, token_map=token_map, detections=detections)

    def restore_text(self, text: str, token_map: dict[str, str]) -> str:
        restored = text
        # Longer tokens first to avoid partial overlaps.
        for token in sorted(token_map.keys(), key=len, reverse=True):
            restored = restored.replace(token, token_map[token])
        return restored

    def _pseudonymize(self, text: str, token_map: dict[str, str]) -> tuple[str, int]:
        detections = 0

        def replace(match: re.Match[str], kind: str) -> str:
            nonlocal detections
            original = match.group(0)
            digest = hmac.new(
                self._secret,
                f"{kind}:{original}".encode(),
                hashlib.sha256,
            ).hexdigest()[:12]
            token = f"⟦{kind.upper()}_{digest}⟧"
            token_map[token] = original
            detections += 1
            return token

        result = EMAIL_RE.sub(lambda m: replace(m, "email"), text)
        result = URL_RE.sub(lambda m: replace(m, "url"), result)
        result = PHONE_RE.sub(lambda m: replace(m, "phone"), result)
        result = ID_RE.sub(lambda m: replace(m, "id"), result)
        return result, detections

    @staticmethod
    def _parse_profile(value: str) -> ProcessingProfile:
        try:
            return ProcessingProfile(value)
        except ValueError as exc:
            raise PolicyBlockedError(
                "Unknown processing profile. Failing closed.",
                details={"profile": value},
            ) from exc

    @staticmethod
    def _parse_data_class(value: str) -> DataClass:
        try:
            return DataClass(value)
        except ValueError as exc:
            raise PolicyBlockedError(
                "Unknown data class. Failing closed.",
                details={"data_class": value},
            ) from exc

    @staticmethod
    def _risk_rank(profile: ProcessingProfile) -> int:
        return {
            ProcessingProfile.BLOCKED: 0,
            ProcessingProfile.MANAGED_NO_LLM: 1,
            ProcessingProfile.GENAI_PSEUDONYMIZED: 2,
            ProcessingProfile.GENAI_SYNTHETIC_POC: 3,
            ProcessingProfile.GENAI_RAW_EXCEPTION: 4,
        }[profile]
