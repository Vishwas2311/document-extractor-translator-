"""Unit tests for the local Data Security Gateway."""

import pytest

from app.core.config import Settings
from app.core.enums import ProcessingProfile
from app.core.exceptions import PolicyBlockedError
from app.schemas.translation import TranslationInput
from app.services.security_gateway import SecurityGateway


def _settings(**overrides: object) -> Settings:
    base = {
        "auth_required": False,
        "api_auth_tokens": "",
        "default_processing_profile": "GENAI_PSEUDONYMIZED",
        "allow_synthetic_raw_llm": True,
        "genai_raw_exception_enabled": False,
        "pseudonymization_secret": "test-secret",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_client_cannot_escalate_to_raw_profile() -> None:
    gateway = SecurityGateway(_settings())
    with pytest.raises(PolicyBlockedError):
        gateway.select_profile(
            data_class="synthetic",
            requested_profile=ProcessingProfile.GENAI_RAW_EXCEPTION.value,
        )


def test_confidential_blocks_synthetic_poc_profile() -> None:
    gateway = SecurityGateway(_settings())
    with pytest.raises(PolicyBlockedError):
        gateway.select_profile(
            data_class="confidential",
            requested_profile=ProcessingProfile.GENAI_SYNTHETIC_POC.value,
        )


def test_deidentified_blocks_synthetic_poc_raw_path() -> None:
    # Deidentified content may only use the pseudonymized route; the raw
    # synthetic-POC path must fail closed even when the synthetic flag is on.
    gateway = SecurityGateway(_settings(allow_synthetic_raw_llm=True))
    with pytest.raises(PolicyBlockedError, match="Failing closed"):
        gateway.select_profile(
            data_class="deidentified",
            requested_profile=ProcessingProfile.GENAI_SYNTHETIC_POC.value,
            trusted_stored=True,
        )


@pytest.mark.parametrize(
    "data_class", ["synthetic", "deidentified", "confidential", "restricted"]
)
def test_raw_exception_is_blocked_for_every_data_class_when_switch_is_off(
    data_class: str,
) -> None:
    gateway = SecurityGateway(_settings(genai_raw_exception_enabled=False))
    with pytest.raises(PolicyBlockedError, match="not enabled"):
        gateway.select_profile(
            data_class=data_class,
            requested_profile=ProcessingProfile.GENAI_RAW_EXCEPTION.value,
            trusted_stored=True,
        )


@pytest.mark.parametrize(
    "data_class", ["synthetic", "deidentified", "confidential", "restricted"]
)
def test_raw_exception_requires_only_the_kill_switch(data_class: str) -> None:
    gateway = SecurityGateway(_settings(genai_raw_exception_enabled=True))
    profile = gateway.select_profile(
        data_class=data_class,
        requested_profile=ProcessingProfile.GENAI_RAW_EXCEPTION.value,
        trusted_stored=True,
    )
    assert profile == ProcessingProfile.GENAI_RAW_EXCEPTION


@pytest.mark.parametrize("data_class", ["deidentified", "confidential", "restricted"])
def test_synthetic_poc_is_blocked_for_every_non_synthetic_class(data_class: str) -> None:
    gateway = SecurityGateway(_settings(allow_synthetic_raw_llm=True))
    with pytest.raises(PolicyBlockedError):
        gateway.select_profile(
            data_class=data_class,
            requested_profile=ProcessingProfile.GENAI_SYNTHETIC_POC.value,
            trusted_stored=True,
        )


def test_synthetic_poc_requires_the_synthetic_raw_flag() -> None:
    gateway = SecurityGateway(_settings(allow_synthetic_raw_llm=False))
    with pytest.raises(PolicyBlockedError, match="disabled"):
        gateway.select_profile(
            data_class="synthetic",
            requested_profile=ProcessingProfile.GENAI_SYNTHETIC_POC.value,
            trusted_stored=True,
        )


@pytest.mark.parametrize(
    "data_class", ["synthetic", "deidentified", "confidential", "restricted"]
)
def test_pseudonymized_route_is_allowed_for_every_data_class(data_class: str) -> None:
    gateway = SecurityGateway(_settings())
    profile = gateway.select_profile(data_class=data_class)
    assert profile == ProcessingProfile.GENAI_PSEUDONYMIZED


def test_unknown_data_class_fails_closed() -> None:
    gateway = SecurityGateway(_settings())
    with pytest.raises(PolicyBlockedError, match="Unknown data class"):
        gateway.select_profile(data_class="mystery")


async def test_multilingual_detector_spans_are_tokenized_and_restored() -> None:
    from collections.abc import Sequence

    from app.services.pii.base import PiiSpan

    class FakeDetector:
        name = "multilingual"

        async def detect_batch(
            self, texts: Sequence[str], *, language: str | None
        ) -> list[list[PiiSpan]]:
            # Pretend the first four characters of each block are a person name -
            # the kind of non-English PII regex cannot catch.
            return [[PiiSpan(0, 4, "Person")] for _ in texts]

    gateway = SecurityGateway(_settings(), detector=FakeDetector())
    inputs = [
        TranslationInput(block_id="b1", source_language="ar", source_text="فلان ذهب"),
    ]
    prepared = await gateway.prepare_translation_inputs(
        ProcessingProfile.GENAI_PSEUDONYMIZED, inputs
    )
    assert prepared.detections == 1
    assert "فلان" not in prepared.inputs[0].source_text
    restored = gateway.restore_text(prepared.inputs[0].source_text, prepared.token_map)
    assert "فلان" in restored


async def test_multilingual_failure_fails_closed() -> None:
    from collections.abc import Sequence

    from app.services.pii.base import PiiSpan

    class FailingDetector:
        name = "multilingual"

        async def detect_batch(
            self, texts: Sequence[str], *, language: str | None
        ) -> list[list[PiiSpan]]:
            raise PolicyBlockedError("detector unavailable")

    gateway = SecurityGateway(_settings(), detector=FailingDetector())
    inputs = [TranslationInput(block_id="b1", source_language="zh", source_text="张三")]
    with pytest.raises(PolicyBlockedError):
        await gateway.prepare_translation_inputs(
            ProcessingProfile.GENAI_PSEUDONYMIZED, inputs
        )


async def test_pseudonymize_and_restore_round_trip() -> None:
    gateway = SecurityGateway(_settings())
    inputs = [
        TranslationInput(
            block_id="b1",
            source_language="en",
            source_text="Contact case@example.com or +1 (555) 123-4567",
        )
    ]
    prepared = await gateway.prepare_translation_inputs(
        ProcessingProfile.GENAI_PSEUDONYMIZED, inputs
    )
    assert prepared.detections >= 2
    assert "case@example.com" not in prepared.inputs[0].source_text
    restored = gateway.restore_text(prepared.inputs[0].source_text, prepared.token_map)
    assert "case@example.com" in restored
