from pydantic import BaseModel, Field


class TranslationInput(BaseModel):
    block_id: str
    source_language: str
    source_text: str


class TranslationBatchRequest(BaseModel):
    target_language: str = "en"
    blocks: list[TranslationInput] = Field(min_length=1)


class TranslationItem(BaseModel):
    block_id: str
    translated_text: str
    detected_language: str | None = Field(
        default=None,
        description=(
            "BCP 47 tag for the language the model actually detected the source text "
            "to be in, which may differ from the declared source_language hint. "
            "'und' or omitted if genuinely undetectable."
        ),
    )


class TranslationBatchResponse(BaseModel):
    translations: list[TranslationItem]
