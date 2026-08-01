import re

from app.core.exceptions import TranslationValidationError
from app.schemas.translation import TranslationBatchResponse, TranslationInput

PROTECTED_RE = re.compile(
    r"https?://[^\s]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b(?:[A-Z]{2,}[A-Z0-9_-]*|[A-Z]+-\d+)\b|\b\d+(?:[.,:/-]\d+)*\b"
)


class TranslationValidator:
    def validate(
        self,
        inputs: list[TranslationInput],
        response: TranslationBatchResponse,
    ) -> None:
        expected_ids = [item.block_id for item in inputs]
        actual_ids = [item.block_id for item in response.translations]
        if actual_ids != expected_ids:
            raise TranslationValidationError(
                "Translation IDs or ordering did not match the input batch."
            )
        if len(set(actual_ids)) != len(actual_ids):
            raise TranslationValidationError("Translation response contained duplicate IDs.")
        source_by_id = {item.block_id: item.source_text for item in inputs}
        for item in response.translations:
            if source_by_id[item.block_id].strip() and not item.translated_text.strip():
                raise TranslationValidationError(f"Translation for {item.block_id} was empty.")
            source_tokens = PROTECTED_RE.findall(source_by_id[item.block_id])
            missing = [token for token in source_tokens if token not in item.translated_text]
            if missing:
                raise TranslationValidationError(
                    f"Translation for {item.block_id} changed protected tokens.",
                    details={"block_id": item.block_id, "missing_tokens": missing[:10]},
                )
