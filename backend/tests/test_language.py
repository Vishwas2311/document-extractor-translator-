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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3", False),
        ("2024-01-15", False),
        ("#42/10", False),
        ("   ", False),
        ("Page 3", True),
        ("مرحبا", True),
        ("青年", True),
    ],
)
def test_has_letters_identifies_non_linguistic_content(text: str, expected: bool) -> None:
    assert LanguageService.has_letters(text) is expected
