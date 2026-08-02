import re

from app.schemas.page import TextBlock

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_RE = re.compile(r"[A-Za-z]")
# Common Traditional-only characters used as a lightweight script heuristic.
TRADITIONAL_MARKERS = set("國語體區們與這來對開關門東車馬魚鳥龍書後發點見貝風長")


class LanguageService:
    def detect(self, text: str, hinted_language: str | None = None) -> str:
        hint = (hinted_language or "").lower().replace("_", "-")
        if hint.startswith("ar"):
            return "ar"
        if hint in {"zh-hant", "zh-cht", "zh-tw", "zh-hk", "zh-mo"}:
            return "zh-Hant"
        if hint in {"zh", "zh-hans", "zh-chs", "zh-cn", "zh-sg"}:
            return "zh-Hans"
        has_arabic = bool(ARABIC_RE.search(text))
        has_han = bool(HAN_RE.search(text))
        has_latin = bool(LATIN_RE.search(text))
        if (has_arabic or has_han) and has_latin:
            return "mixed"
        if has_arabic and has_han:
            return "mixed"
        if has_arabic:
            return "ar"
        if has_han:
            if any(character in TRADITIONAL_MARKERS for character in text):
                return "zh-Hant"
            return "zh-Hans"
        if has_latin:
            return "en"
        return "und"

    def enrich(self, blocks: list[TextBlock]) -> list[TextBlock]:
        for block in blocks:
            block.source_language = self.detect(block.source_text, block.source_language)
        return blocks

    @staticmethod
    def should_translate(language: str) -> bool:
        return language in {"ar", "zh-Hans", "zh-Hant", "zh", "mixed"}

    @staticmethod
    def has_letters(text: str) -> bool:
        """True if text contains at least one alphabetic character in any script."""
        return any(character.isalpha() for character in text)
