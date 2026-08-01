from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    document_id: str | None = None
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
