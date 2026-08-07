import pytest

from app.services.language import LanguageService


@pytest.mark.parametrize(
    ("text", "hint", "expected"),
    [
        ("مرحبا بكم", None, "ar"),
        ("青年支持计划", None, "zh-Hans"),
        ("Youth support", None, "und"),
        ("Youth support", "en-US", "en"),
        ("Case 12: مرحبا", None, "mixed"),
        ("content", "ar-SA", "ar"),
        ("content", "zh-Hans", "zh-Hans"),
        ("Bonjour", "fr-FR", "fr-FR"),
        ("नमस्ते", "hi", "hi"),
        ("Привет", "ru-RU", "ru-RU"),
        ("Hola", "es_419", "es-419"),
        ("Olá", "pt-BR", "pt-BR"),
    ],
)
def test_detects_provider_languages_and_script_fallbacks(
    text: str,
    hint: str | None,
    expected: str,
) -> None:
    assert LanguageService().detect(text, hint) == expected


@pytest.mark.parametrize(
    "language",
    ["ar", "zh-Hans", "mixed", "fr-FR", "hi", "ru-RU", "es-419", "pt-BR"],
)
def test_any_valid_detected_non_english_language_is_translated(language: str) -> None:
    assert LanguageService.should_translate(language)


@pytest.mark.parametrize("language", ["en", "en-US", "und", "zxx", "invalid language"])
def test_non_translatable_or_unknown_language_is_not_routed(language: str) -> None:
    assert not LanguageService.should_translate(language)


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
