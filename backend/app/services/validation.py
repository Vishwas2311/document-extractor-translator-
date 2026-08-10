import re

from app.core.exceptions import TranslationValidationError
from app.schemas.translation import TranslationBatchResponse, TranslationInput
from app.services.security_gateway import PSEUDONYM_TOKEN_RE

# The `[A-Z]{2,}[A-Z0-9_-]*` alternative below cannot anchor a pseudonym token like
# "⟦ID_a3f9c2d1e4b5⟧": every character from the kind prefix through the hex digest is
# a \w character (letters, digits, underscore), so there is no internal \b boundary for
# the closing \b to land on, and the token matches none of the existing alternatives at
# all - not even the kind prefix. PSEUDONYM_TOKEN_RE closes that gap explicitly.
PROTECTED_RE = re.compile(
    r"https?://[^\s]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
    r"\b(?:[A-Z]{2,}[A-Z0-9_-]*|[A-Z]+-\d+)\b|\b\d+(?:[.,:/-]\d+)*\b|"
    + PSEUDONYM_TOKEN_RE.pattern
)


class TranslationValidator:
    def validate(
        self,
        inputs: list[TranslationInput],
        response: TranslationBatchResponse,
    ) -> None:
        expected_ids = [item.block_id for item in inputs]
        actual_ids = [item.block_id for item in response.translations]
        if sorted(actual_ids) != sorted(expected_ids):
            # Structured output guarantees a schema-valid response, not identical item
            # order - downstream consumption is by block_id (a dict lookup), so a
            # complete, correctly-translated response returned in a different order is
            # not an error. sorted() (not set()) still catches a duplicate silently
            # replacing a missing ID, which a set-equality check would miss.
            raise TranslationValidationError(
                "Translation IDs did not match the input batch (missing, extra, or duplicate IDs)."
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
