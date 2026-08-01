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


class TranslationBatchResponse(BaseModel):
    translations: list[TranslationItem]
