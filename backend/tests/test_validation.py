import pytest

from app.core.exceptions import TranslationValidationError
from app.schemas.translation import TranslationBatchResponse, TranslationInput, TranslationItem
from app.services.validation import TranslationValidator


def test_accepts_ordered_translation_with_protected_tokens() -> None:
    inputs = [
        TranslationInput(
            block_id="b1",
            source_language="ar",
            source_text="الملف CASE-42 بتاريخ 14/03/2010",
        )
    ]
    response = TranslationBatchResponse(
        translations=[
            TranslationItem(
                block_id="b1",
                translated_text="File CASE-42 dated 14/03/2010",
            )
        ]
    )

    TranslationValidator().validate(inputs, response)


def test_rejects_missing_or_reordered_ids() -> None:
    inputs = [
        TranslationInput(block_id="b1", source_language="ar", source_text="مرحبا"),
        TranslationInput(block_id="b2", source_language="zh-Hans", source_text="你好"),
    ]
    response = TranslationBatchResponse(
        translations=[
            TranslationItem(block_id="b2", translated_text="Hello"),
            TranslationItem(block_id="b1", translated_text="Welcome"),
        ]
    )

    with pytest.raises(TranslationValidationError):
        TranslationValidator().validate(inputs, response)


def test_rejects_changed_protected_tokens() -> None:
    inputs = [TranslationInput(block_id="b1", source_language="ar", source_text="CASE-42")]
    response = TranslationBatchResponse(
        translations=[TranslationItem(block_id="b1", translated_text="Case forty-two")]
    )

    with pytest.raises(TranslationValidationError):
        TranslationValidator().validate(inputs, response)
