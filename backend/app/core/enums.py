from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    EXTRACTING = "extracting"
    NORMALIZING = "normalizing"
    TRANSLATING = "translating"
    VALIDATING = "validating"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ProcessingStage(StrEnum):
    QUEUED = "queued"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    TRANSLATION = "translation"
    VALIDATION = "validation"
    EXPORT = "export"
    COMPLETED = "completed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TranslationStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    TRANSLATED = "translated"
    FAILED = "failed"
    FILTERED = "filtered"
    NEEDS_REVIEW = "needs_review"


TERMINAL_DOCUMENT_STATUSES = {
    DocumentStatus.COMPLETED,
    DocumentStatus.NEEDS_REVIEW,
    DocumentStatus.FAILED,
}
