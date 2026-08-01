import re

from app.schemas.page import TextBlock

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_RE = re.compile(r"[A-Za-z]")


class LanguageService:
    def detect(self, text: str, hinted_language: str | None = None) -> str:
        hint = (hinted_language or "").lower()
        if hint.startswith("ar"):
            return "ar"
        if hint in {"zh", "zh-hans", "zh_chs"}:
            return "zh-Hans"
        if hint in {"zh-hant", "zh_cht"}:
            return "zh-Hant"
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
