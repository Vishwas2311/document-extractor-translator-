import pytest

from app.core.config import Settings
from app.core.enums import ProcessingProfile
from app.core.exceptions import TranslationValidationError
from app.schemas.translation import TranslationBatchResponse, TranslationInput, TranslationItem
from app.services.security_gateway import PSEUDONYM_TOKEN_RE, SecurityGateway
from app.services.validation import PROTECTED_RE, TranslationValidator


def _gateway() -> SecurityGateway:
    return SecurityGateway(
        Settings(
            auth_required=False,
            api_auth_tokens="",
            default_processing_profile="GENAI_PSEUDONYMIZED",
            allow_synthetic_raw_llm=True,
            genai_raw_exception_enabled=False,
            pseudonymization_secret="test-secret",
        )
    )


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


def test_accepts_reordered_but_complete_id_set() -> None:
    # Structured output guarantees schema-valid JSON, not identical item order.
    # Downstream consumption is by block_id dict lookup, so a complete, correctly
    # translated response returned in a different order must not be rejected.
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

    TranslationValidator().validate(inputs, response)


def test_rejects_missing_or_extra_ids() -> None:
    inputs = [
        TranslationInput(block_id="b1", source_language="ar", source_text="مرحبا"),
        TranslationInput(block_id="b2", source_language="zh-Hans", source_text="你好"),
    ]
    response = TranslationBatchResponse(
        translations=[TranslationItem(block_id="b1", translated_text="Welcome")]
    )

    with pytest.raises(TranslationValidationError):
        TranslationValidator().validate(inputs, response)


def test_rejects_duplicate_ids_replacing_a_missing_one() -> None:
    # A plain set(actual) != set(expected) comparison would miss this: {"b1"} == {"b1"}
    # even though b2's translation is silently missing and b1 is duplicated instead.
    inputs = [
        TranslationInput(block_id="b1", source_language="ar", source_text="مرحبا"),
        TranslationInput(block_id="b2", source_language="zh-Hans", source_text="你好"),
    ]
    response = TranslationBatchResponse(
        translations=[
            TranslationItem(block_id="b1", translated_text="Welcome"),
            TranslationItem(block_id="b1", translated_text="Welcome again"),
        ]
    )

    with pytest.raises(TranslationValidationError):
        TranslationValidator().validate(inputs, response)


def test_rejects_changed_protected_tokens() -> None:
    # A single block's protected-token drift is reported per-block, not raised for
    # the whole batch, so the rest of a multi-block batch can still commit.
    inputs = [TranslationInput(block_id="b1", source_language="ar", source_text="CASE-42")]
    response = TranslationBatchResponse(
        translations=[TranslationItem(block_id="b1", translated_text="Case forty-two")]
    )

    invalid = TranslationValidator().validate(inputs, response)
    assert "b1" in invalid


async def _pseudonymize_single(
    gateway: SecurityGateway, text: str
) -> tuple[str, str, dict[str, str]]:
    prepared = await gateway.prepare_translation_inputs(
        ProcessingProfile.GENAI_PSEUDONYMIZED,
        [TranslationInput(block_id="b1", source_language="en", source_text=text)],
    )
    pseudonymized = prepared.inputs[0].source_text
    token = next(iter(prepared.token_map))
    return pseudonymized, token, prepared.token_map


async def test_protected_re_matches_full_pseudonym_token() -> None:
    # Every character from the kind prefix through the hex digest is a \w character,
    # so the pre-existing [A-Z]{2,}[A-Z0-9_-]* alternative has no internal \b boundary
    # to anchor on and matches none of a real token - not even its "ID_" prefix.
    gateway = _gateway()
    _, token, _ = await _pseudonymize_single(gateway, "Case reference 20261225")
    assert PSEUDONYM_TOKEN_RE.fullmatch(token)
    assert PROTECTED_RE.findall(token) == [token]


async def test_rejects_truncated_pseudonym_token() -> None:
    gateway = _gateway()
    text, token, _ = await _pseudonymize_single(gateway, "Reference number 20261225")
    inputs = [TranslationInput(block_id="b1", source_language="en", source_text=text)]
    response = TranslationBatchResponse(
        translations=[
            TranslationItem(block_id="b1", translated_text=text.replace(token, token[:-4]))
        ]
    )

    invalid = TranslationValidator().validate(inputs, response)
    assert "b1" in invalid


async def test_rejects_pseudonym_token_with_altered_digest() -> None:
    gateway = _gateway()
    text, token, _ = await _pseudonymize_single(gateway, "Reference number 20261225")
    altered = token[:-2] + ("0" if token[-2] != "0" else "1") + token[-1]
    inputs = [TranslationInput(block_id="b1", source_language="en", source_text=text)]
    response = TranslationBatchResponse(
        translations=[TranslationItem(block_id="b1", translated_text=text.replace(token, altered))]
    )

    invalid = TranslationValidator().validate(inputs, response)
    assert "b1" in invalid


async def test_pseudonymize_translate_validate_restore_round_trip() -> None:
    gateway = _gateway()
    # The digit run must be set off by punctuation from surrounding Han text - a bare
    # 6+-digit run directly abutting Han characters on both sides has no \b boundary
    # under Unicode regex and would never reach pseudonymization in the first place.
    inputs = [
        TranslationInput(
            block_id="b1", source_language="zh-Hans", source_text="账户余额：20261225"
        )
    ]
    prepared = await gateway.prepare_translation_inputs(
        ProcessingProfile.GENAI_PSEUDONYMIZED, inputs
    )
    pseudonymized_text = prepared.inputs[0].source_text
    token = next(iter(prepared.token_map))
    assert token in pseudonymized_text

    # A translator that preserves the token verbatim passes validation, and the real
    # value is recovered on restore.
    response = TranslationBatchResponse(
        translations=[
            TranslationItem(
                block_id="b1", translated_text=pseudonymized_text.replace("账户余额：", "Balance: ")
            )
        ]
    )
    invalid = TranslationValidator().validate(prepared.inputs, response)
    assert invalid == {}
    restored = gateway.restore_text(response.translations[0].translated_text, prepared.token_map)
    assert "20261225" in restored

    # A translator that garbles the token must be caught here, not silently pass
    # through to restore_text's exact-string replace (which would just leave the
    # garbled placeholder in the delivered translation).
    garbled_response = TranslationBatchResponse(
        translations=[
            TranslationItem(
                block_id="b1",
                translated_text=pseudonymized_text.replace("账户余额：", "Balance: ").replace(
                    token, token[:-4]
                ),
            )
        ]
    )
    invalid = TranslationValidator().validate(prepared.inputs, garbled_response)
    assert "b1" in invalid
