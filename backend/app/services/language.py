import re

from app.schemas.page import TextBlock

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_RE = re.compile(r"[A-Za-z]")
LOCALE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
# Common Traditional-only characters used as a lightweight script heuristic.
TRADITIONAL_MARKERS = set("國語體區們與這來對開關門東車馬魚鳥龍書後發點見貝風長")

# Languages this pipeline has been validated against for production use (see
# docs/DATA-SECURITY.md's "benchmark-gated" production requirement - Arabic and
# both Chinese variants are the mandatory regression fixtures). This is a
# visibility flag only: a language outside this set still translates normally
# (should_translate() doesn't consult it), it's just marked for review instead of
# silently accepted.
BENCHMARKED_LANGUAGES = frozenset({"ar", "zh-Hans", "zh-Hant", "en"})


class LanguageService:
    @staticmethod
    def _normalize_hint(hinted_language: str | None) -> str | None:
        raw = (hinted_language or "").strip().replace("_", "-")
        if not raw or raw.casefold() == "und":
            return None
        lowered = raw.casefold()
        if lowered == "mixed":
            return "mixed"
        if lowered == "zxx":
            return "zxx"
        if lowered.startswith("ar"):
            return "ar"
        if lowered in {"zh-hant", "zh-cht", "zh-tw", "zh-hk", "zh-mo"}:
            return "zh-Hant"
        if lowered in {"zh", "zh-hans", "zh-chs", "zh-cn", "zh-sg"}:
            return "zh-Hans"
        if lowered.startswith("en"):
            return "en"
        if not LOCALE_RE.fullmatch(raw):
            return None
        parts = raw.split("-")
        normalized = [parts[0].lower()]
        for part in parts[1:]:
            if len(part) == 4 and part.isalpha():
                normalized.append(part.title())
            elif len(part) == 2 and part.isalpha():
                normalized.append(part.upper())
            else:
                normalized.append(part.lower())
        return "-".join(normalized)

    def detect(self, text: str, hinted_language: str | None = None) -> str:
        if not self.has_letters(text):
            # No alphabetic content at all (numbers, dashes, punctuation) - never
            # linguistic, regardless of what hint Document Intelligence attached to
            # this span. Must be checked before trusting any hint below, or a
            # spurious hint on a non-linguistic span would masquerade as a real
            # language instead of "zxx".
            return "zxx"
        hint = self._normalize_hint(hinted_language)
        has_arabic = bool(ARABIC_RE.search(text))
        has_han = bool(HAN_RE.search(text))
        has_latin = bool(LATIN_RE.search(text))
        if hint == "en" and (has_arabic or has_han):
            return "mixed"
        if hint == "en" and not has_latin and not has_arabic and not has_han:
            # DI tagged this "en" but the visible script has no Latin letters at
            # all (Cyrillic, Hangul, Devanagari, Thai, ...). An "en" hint that
            # contradicts the actual script isn't trustworthy - treat it as
            # uncertain and let the translation model detect and translate it
            # properly, rather than silently skipping translation on a bad hint.
            return "und"
        if hint is not None and hint.split("-")[0] in {"lzh", "yue"}:
            # Classical/Literary Chinese and Cantonese hints are real DI output on
            # formal-register modern text (e.g. spelled-out RMB amounts get tagged
            # "lzh") - fold to the script-detected zh-Hant/zh-Hans bucket so dedup and
            # the translation prompt treat them like any other Chinese block, instead
            # of fragmenting on a distinct tag or risking archaic-register output.
            if has_han:
                return self._han_script(text)
        if hint is not None:
            return hint
        if (has_arabic or has_han) and has_latin:
            return "mixed"
        if has_arabic and has_han:
            return "mixed"
        if has_arabic:
            return "ar"
        if has_han:
            return self._han_script(text)
        # Text has letters (checked at the top) but they're Latin-only (could be
        # French, German, pinyin, ...) or some other script this heuristic doesn't
        # recognize. Rather than guessing or blocking translation, tag it "und" and
        # let should_translate() route it to the translation model, which can
        # detect and translate far more languages than this heuristic ever will.
        return "und"

    @staticmethod
    def _han_script(text: str) -> str:
        if any(character in TRADITIONAL_MARKERS for character in text):
            return "zh-Hant"
        return "zh-Hans"

    def enrich(self, blocks: list[TextBlock]) -> list[TextBlock]:
        for block in blocks:
            block.source_language = self.detect(block.source_text, block.source_language)
        return blocks

    @staticmethod
    def should_translate(language: str) -> bool:
        """Whether this block needs a translation attempt. Default is yes: only skip
        locally for content confidently identified as already-English or
        non-linguistic (zxx). Everything else - including "und" (a script this
        heuristic doesn't recognize) - is sent to the translation model rather than
        blocked locally, since the model can detect and translate far more languages
        than a handful of regexes ever will; a new/unrecognized script must mean
        "let the model figure it out," never "translation never attempted."""
        normalized = LanguageService._normalize_hint(language)
        return normalized not in {"en", "zxx"}

    @staticmethod
    def has_letters(text: str) -> bool:
        """True if text contains at least one alphabetic character in any script."""
        return any(character.isalpha() for character in text)

    @staticmethod
    def normalize_detected_language(value: str | None) -> str | None:
        """Normalize a language tag the translation model reported it detected, so it
        renders with the same labels/folding as locally-detected languages. Returns
        None if the model didn't report one or reported "und"/unparseable."""
        return LanguageService._normalize_hint(value)

    @staticmethod
    def is_benchmarked(language: str) -> bool:
        """Whether this (already-resolved) language is in the validated set. Flag-only
        signal for review routing - never gates translation itself."""
        normalized = LanguageService._normalize_hint(language)
        return normalized in BENCHMARKED_LANGUAGES
