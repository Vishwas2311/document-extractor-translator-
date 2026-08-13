import re
from collections import Counter

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
    ) -> dict[str, str]:
        """Validate a batch response. Structural problems that make the response as a
        whole unusable for id-based lookup (missing/extra/duplicate ids) still raise -
        the batch can't be safely attributed at all. Per-item problems (empty
        translation, a protected token that changed) instead return a
        {block_id: reason} map so the caller can fail only those specific blocks and
        still commit the rest of the batch, which one bad numeric/acronym token
        shouldn't hold hostage."""
        expected_ids = [item.block_id for item in inputs]
        actual_ids = [item.block_id for item in response.translations]
        if sorted(actual_ids) != sorted(expected_ids):
            # Structured output guarantees a schema-valid response, not identical item
            # order - downstream consumption is by block_id (a dict lookup), so a
            # complete, correctly-translated response returned in a different order is
            # not an error. Counter (not set()) still catches a duplicate silently
            # replacing a missing ID, which a set-equality check would miss, and lets
            # the raised error report exactly which IDs were missing/extra/duplicated
            # instead of just "they didn't match" - the raw model response that would
            # otherwise explain a mismatch isn't kept around past this call.
            expected_counts = Counter(expected_ids)
            actual_counts = Counter(actual_ids)
            missing_ids = sorted((expected_counts - actual_counts).elements())
            extra_ids = sorted((actual_counts - expected_counts).elements())
            duplicate_ids = sorted(
                id_ for id_, count in actual_counts.items() if count > 1
            )
            raise TranslationValidationError(
                "Translation IDs did not match the input batch (missing, extra, or duplicate IDs).",
                details={
                    "missing_ids": missing_ids,
                    "extra_ids": extra_ids,
                    "duplicate_ids": duplicate_ids,
                },
            )
        if len(set(actual_ids)) != len(actual_ids):
            raise TranslationValidationError("Translation response contained duplicate IDs.")
        source_by_id = {item.block_id: item.source_text for item in inputs}
        invalid: dict[str, str] = {}
        for item in response.translations:
            if source_by_id[item.block_id].strip() and not item.translated_text.strip():
                invalid[item.block_id] = "Translation was empty; needs manual review."
                continue
            source_tokens = PROTECTED_RE.findall(source_by_id[item.block_id])
            missing = [token for token in source_tokens if token not in item.translated_text]
            if missing:
                invalid[item.block_id] = (
                    "Translation changed a protected value (a number, code, or "
                    "identifier); needs manual review."
                )
        return invalid
