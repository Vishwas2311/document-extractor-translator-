import pytest

from app.services.language import LanguageService


@pytest.mark.parametrize(
    ("text", "hint", "expected"),
    [
        ("مرحبا بكم", None, "ar"),
        ("青年支持计划", None, "zh-Hans"),
        # No DI hint and no script this heuristic recognizes as a known bucket
        # (Latin-only, Cyrillic, Hangul, ...) all fall to "und" - should_translate()
        # (tested below) still routes these to the translation model instead of
        # blocking them, so a script the local heuristic has never seen still gets
        # translated correctly rather than stalling forever.
        ("Youth support", None, "und"),
        ("Youth support", "en-US", "en"),
        ("2024-01-15", None, "zxx"),
        # A hint attached to non-linguistic content must never override "zxx" - it's
        # checked before any hint is consulted at all.
        ("2024-01-15", "zh-Hans", "zxx"),
        ("---", "ar-SA", "zxx"),
        ("Привет", None, "und"),
        ("안녕하세요", None, "und"),
        # An "en" hint that contradicts the actual script (no Latin letters at all)
        # isn't trustworthy - treated as uncertain ("und") rather than silently
        # skipping translation on a bad hint.
        ("Привет", "en-US", "und"),
        ("안녕하세요", "en", "und"),
        ("Case 12: مرحبا", None, "mixed"),
        ("content", "ar-SA", "ar"),
        ("content", "zh-Hans", "zh-Hans"),
        ("Bonjour", "fr-FR", "fr-FR"),
        ("नमस्ते", "hi", "hi"),
        ("Привет", "ru-RU", "ru-RU"),
        ("Hola", "es_419", "es-419"),
        ("Olá", "pt-BR", "pt-BR"),
        # Azure DI tags formal-register modern Chinese (e.g. spelled-out RMB amounts)
        # as "lzh" (Classical/Literary Chinese) in real output - fold to the
        # script-detected bucket instead of fragmenting on a distinct tag.
        ("人民币壹万陆仟肆佰零肆元叁角整", "lzh", "zh-Hans"),
        ("國語體區這來對", "lzh", "zh-Hant"),
        ("你好", "yue", "zh-Hans"),
        ("國語體區這來對", "yue-HK", "zh-Hant"),
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
    ["ar", "zh-Hans", "mixed", "fr-FR", "hi", "ru-RU", "es-419", "pt-BR", "lzh", "yue"],
)
def test_any_valid_detected_non_english_language_is_translated(language: str) -> None:
    # "lzh"/"yue" as raw, undetected values must still route for translation - the
    # detect()-time folding to zh-Hant/zh-Hans is a separate concern from this
    # should_translate check never dropping a block outright.
    assert LanguageService.should_translate(language)


@pytest.mark.parametrize("language", ["en", "en-US", "zxx"])
def test_confidently_english_or_non_linguistic_content_is_not_routed(language: str) -> None:
    assert not LanguageService.should_translate(language)


@pytest.mark.parametrize("language", ["und", "invalid language", "ko-KR", "th-TH", ""])
def test_unrecognized_or_unhinted_language_is_still_routed_for_translation(
    language: str,
) -> None:
    # "und" (a script the local heuristic doesn't recognize), a malformed hint, or a
    # locale we've simply never special-cased must all still reach the translation
    # model rather than being silently blocked - only "en" and "zxx" are skipped
    # locally. This is what lets a brand-new language work correctly without any
    # code change here.
    assert LanguageService.should_translate(language)


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


@pytest.mark.parametrize("language", ["ar", "zh-Hans", "zh-Hant", "en", "en-US", "AR"])
def test_is_benchmarked_accepts_validated_languages(language: str) -> None:
    assert LanguageService.is_benchmarked(language)


@pytest.mark.parametrize("language", ["fr-FR", "ru-RU", "ko-KR", "und", "zxx", "hi"])
def test_is_benchmarked_flags_everything_else(language: str) -> None:
    # Flag-only signal: is_benchmarked() being False doesn't block translation (see
    # should_translate) - it only marks the result for review.
    assert not LanguageService.is_benchmarked(language)
