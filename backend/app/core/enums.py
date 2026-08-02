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


class ProcessingProfile(StrEnum):
    """Backend-enforced AI processing profile (client cannot downgrade)."""

    GENAI_PSEUDONYMIZED = "GENAI_PSEUDONYMIZED"
    GENAI_SYNTHETIC_POC = "GENAI_SYNTHETIC_POC"
    GENAI_RAW_EXCEPTION = "GENAI_RAW_EXCEPTION"
    MANAGED_NO_LLM = "MANAGED_NO_LLM"
    BLOCKED = "BLOCKED"


class DataClass(StrEnum):
    SYNTHETIC = "synthetic"
    DEIDENTIFIED = "deidentified"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RetryMode(StrEnum):
    RESUME = "resume"
    RETRANSLATE = "retranslate"
    REPROCESS = "reprocess"
