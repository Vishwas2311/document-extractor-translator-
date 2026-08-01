import pytest

from app.services.language import LanguageService


@pytest.mark.parametrize(
    ("text", "hint", "expected"),
    [
        ("مرحبا بكم", None, "ar"),
        ("青年支持计划", None, "zh-Hans"),
        ("Youth support", None, "en"),
        ("Case 12: مرحبا", None, "mixed"),
        ("content", "ar-SA", "ar"),
        ("content", "zh-Hans", "zh-Hans"),
    ],
)
def test_detects_supported_languages(text: str, hint: str | None, expected: str) -> None:
    assert LanguageService().detect(text, hint) == expected


def test_only_supported_languages_are_translated() -> None:
    service = LanguageService()
    assert service.should_translate("ar")
    assert service.should_translate("zh-Hans")
    assert service.should_translate("mixed")
    assert not service.should_translate("en")
