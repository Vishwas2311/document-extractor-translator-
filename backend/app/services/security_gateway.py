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
from app.services.pii import PiiDetector, PiiSpan, build_pii_detector, dedupe_overlaps

# Matches a pseudonym token as generated in `_tokenize` below (e.g. "⟦ID_a3f9c2d1e4b5⟧").
# Single source of truth for the token shape, reused by validation.py's round-trip
# integrity check so the two can never silently drift apart.
PSEUDONYM_TOKEN_RE = re.compile(r"⟦[A-Z]+_[0-9a-f]{12}⟧")

# Explicit allow-matrix for generative profiles: any (data_class, profile)
# combination not listed here fails closed. MANAGED_NO_LLM and BLOCKED are not
# generative routes - they are rejected below with their own specific messages.
# GENAI_RAW_EXCEPTION additionally requires the kill switch for EVERY data class,
# and GENAI_SYNTHETIC_POC (raw text) is allowed for synthetic data only -
# deidentified content must use the pseudonymized route.
GENAI_PROFILE_ALLOW_MATRIX: dict[DataClass, frozenset[ProcessingProfile]] = {
    DataClass.SYNTHETIC: frozenset(
        {
            ProcessingProfile.GENAI_PSEUDONYMIZED,
            ProcessingProfile.GENAI_SYNTHETIC_POC,
            ProcessingProfile.GENAI_RAW_EXCEPTION,
        }
    ),
    DataClass.DEIDENTIFIED: frozenset(
        {
            ProcessingProfile.GENAI_PSEUDONYMIZED,
            ProcessingProfile.GENAI_RAW_EXCEPTION,
        }
    ),
    DataClass.CONFIDENTIAL: frozenset(
        {
            ProcessingProfile.GENAI_PSEUDONYMIZED,
            ProcessingProfile.GENAI_RAW_EXCEPTION,
        }
    ),
    DataClass.RESTRICTED: frozenset(
        {
            ProcessingProfile.GENAI_PSEUDONYMIZED,
            ProcessingProfile.GENAI_RAW_EXCEPTION,
        }
    ),
}


@dataclass
class PseudonymizationResult:
    inputs: list[TranslationInput]
    token_map: dict[str, str] = field(default_factory=dict)
    detections: int = 0


class SecurityGateway:
    def __init__(self, settings: Settings, detector: PiiDetector | None = None) -> None:
        self.settings = settings
        self._detector = detector if detector is not None else build_pii_detector(settings)
        secret = settings.pseudonymization_secret
        if not secret:
            # No configured secret: never fall back to a public, install-identical
            # value (the app name) — that makes pseudonym tokens predictable and
            # identical across every deployment. Use a per-process random secret so
            # local demos still run, while production is separately forced (config
            # validation) to require a strong, externally managed secret.
            import secrets

            secret = secrets.token_urlsafe(48)
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

        if profile not in {ProcessingProfile.MANAGED_NO_LLM, ProcessingProfile.BLOCKED}:
            allowed = GENAI_PROFILE_ALLOW_MATRIX.get(classified)
            if allowed is None or profile not in allowed:
                raise PolicyBlockedError(
                    "No approved processing profile for this data class. Failing closed.",
                    details={"data_class": classified.value, "profile": profile.value},
                )
            if (
                profile == ProcessingProfile.GENAI_RAW_EXCEPTION
                and not self.settings.genai_raw_exception_enabled
            ):
                raise PolicyBlockedError(
                    "Raw generative LLM exception is not enabled.",
                    details={"data_class": classified.value},
                )
            if (
                profile == ProcessingProfile.GENAI_SYNTHETIC_POC
                and not self.settings.allow_synthetic_raw_llm
            ):
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

    async def prepare_translation_inputs(
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
        prepared: list[TranslationInput | None] = [None] * len(inputs)
        detections = 0

        # Group by source language so a language-aware detector gets the right hint,
        # and only make one detection call per language group.
        groups: dict[str | None, list[int]] = {}
        for index, item in enumerate(inputs):
            groups.setdefault(item.source_language, []).append(index)

        for language, indices in groups.items():
            texts = [inputs[i].source_text for i in indices]
            spans_by_text = await self._detector.detect_batch(texts, language=language)
            for local_index, source_index in enumerate(indices):
                item = inputs[source_index]
                new_text, found = self._tokenize(
                    item.source_text, spans_by_text[local_index], token_map
                )
                detections += found
                prepared[source_index] = TranslationInput(
                    block_id=item.block_id,
                    source_language=item.source_language,
                    source_text=new_text,
                )

        finalized = [item for item in prepared if item is not None]
        return PseudonymizationResult(
            inputs=finalized, token_map=token_map, detections=detections
        )

    def restore_text(self, text: str, token_map: dict[str, str]) -> str:
        restored = text
        # Longer tokens first to avoid partial overlaps.
        for token in sorted(token_map.keys(), key=len, reverse=True):
            restored = restored.replace(token, token_map[token])
        return restored

    def _tokenize(
        self, text: str, spans: list[PiiSpan], token_map: dict[str, str]
    ) -> tuple[str, int]:
        safe_spans = dedupe_overlaps(spans)
        if not safe_spans:
            return text, 0
        detections = 0
        result = text
        # Replace right-to-left so earlier spans' indices stay valid.
        for span in sorted(safe_spans, key=lambda s: s.start, reverse=True):
            original = text[span.start : span.end]
            if not original:
                continue
            kind = re.sub(r"[^A-Za-z]", "", span.category).upper() or "PII"
            digest = hmac.new(
                self._secret,
                f"{kind}:{original}".encode(),
                hashlib.sha256,
            ).hexdigest()[:12]
            token = f"⟦{kind}_{digest}⟧"
            token_map[token] = original
            result = result[: span.start] + token + result[span.end :]
            detections += 1
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
