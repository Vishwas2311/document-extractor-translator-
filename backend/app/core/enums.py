from enum import StrEnum


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    CLASSIFYING = "classifying"
    EXTRACTING = "extracting"
    NORMALIZING = "normalizing"
    TRANSLATING = "translating"
    VALIDATING = "validating"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingStage(StrEnum):
    QUEUED = "queued"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    TRANSLATION = "translation"
    VALIDATION = "validation"
    EXPORT = "export"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


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
    DocumentStatus.CANCELLED,
}

RETRIABLE_DOCUMENT_STATUSES = {
    DocumentStatus.FAILED,
    DocumentStatus.NEEDS_REVIEW,
    DocumentStatus.CANCELLED,
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


class FinancialPageDisposition(StrEnum):
    """Backend decision describing how a source page is processed."""

    FINANCIAL = "financial"
    NON_FINANCIAL = "non_financial"
    UNCERTAIN = "uncertain"


class FinancialReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentReviewStatus(StrEnum):
    """Human workflow status (orthogonal to machine DocumentStatus)."""

    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssignmentStatus(StrEnum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    CLAIMED = "claimed"
