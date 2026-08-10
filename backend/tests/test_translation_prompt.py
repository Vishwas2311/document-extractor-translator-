from app.prompts.translation import TRANSLATION_DEVELOPER_PROMPT, TRANSLATION_PROMPT_VERSION

# Pinned to the version in place before the CJK consistency guidance was added. If this
# fails, the prompt text changed without bumping TRANSLATION_PROMPT_VERSION - the
# translation cache key in processing.py is derived from this version string, so
# skipping the bump would silently keep serving stale cached translations under the
# old prompt forever, and the new guidance would never take effect.
_PRIOR_VERSION = "translation-v3-multilingual-format-aware"


def test_prompt_version_was_bumped_for_the_cjk_consistency_guidance() -> None:
    assert TRANSLATION_PROMPT_VERSION != _PRIOR_VERSION


def test_prompt_includes_script_preservation_and_consistency_guidance() -> None:
    assert "Traditional" in TRANSLATION_DEVELOPER_PROMPT
    assert "Simplified" in TRANSLATION_DEVELOPER_PROMPT
    assert "identically every time" in TRANSLATION_DEVELOPER_PROMPT
