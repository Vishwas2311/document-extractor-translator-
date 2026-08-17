"""Settings validation tests."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_target_language_english_is_accepted() -> None:
    settings = Settings(auth_required=False, target_language="en")
    assert settings.target_language == "en"


def test_non_english_target_language_fails_closed_at_startup() -> None:
    # The prompt and translation schema are hard-wired to English; any other
    # configured target would be silently ignored, so startup must reject it.
    with pytest.raises(ValidationError, match="only supported"):
        Settings(auth_required=False, target_language="fr")


def test_production_configuration_fails_closed_on_local_adapters() -> None:
    with pytest.raises(ValidationError, match="Unsafe production configuration"):
        Settings(app_env="production", auth_required=True)


def test_entra_auth_requires_complete_identity_configuration() -> None:
    with pytest.raises(ValidationError, match="Entra JWT authentication is incomplete"):
        Settings(auth_mode="entra_jwt", auth_required=True)


def test_unknown_adapter_names_fail_at_startup() -> None:
    with pytest.raises(ValidationError, match="STORAGE_BACKEND"):
        Settings(auth_required=False, storage_backend="magic_disk")
