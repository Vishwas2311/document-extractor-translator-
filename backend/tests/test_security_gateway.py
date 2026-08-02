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


def test_pseudonymize_and_restore_round_trip() -> None:
    gateway = SecurityGateway(_settings())
    inputs = [
        TranslationInput(
            block_id="b1",
            source_language="en",
            source_text="Contact case@example.com or +1 (555) 123-4567",
        )
    ]
    prepared = gateway.prepare_translation_inputs(ProcessingProfile.GENAI_PSEUDONYMIZED, inputs)
    assert prepared.detections >= 2
    assert "case@example.com" not in prepared.inputs[0].source_text
    restored = gateway.restore_text(prepared.inputs[0].source_text, prepared.token_map)
    assert "case@example.com" in restored
