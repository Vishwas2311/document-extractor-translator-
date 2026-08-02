from typing import Any


class AppError(Exception):
    """Base safe application exception."""

    code = "application_error"
    status_code = 500
    retryable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AppError):
    code = "configuration_missing"
    status_code = 503


class DocumentNotFoundError(AppError):
    code = "document_not_found"
    status_code = 404


class InvalidDocumentError(AppError):
    code = "invalid_document"
    status_code = 422


class ConflictError(AppError):
    code = "document_conflict"
    status_code = 409


class JobNotFoundError(AppError):
    code = "job_not_found"
    status_code = 404


class JobLeaseLostError(AppError):
    """Raised when a worker's job lease was reclaimed (expired) by another worker."""

    code = "job_lease_lost"
    status_code = 409
    retryable = True


class AzureServiceError(AppError):
    code = "azure_service_error"
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retryable = retryable


class TranslationValidationError(AppError):
    code = "translation_output_invalid"
    status_code = 502
    retryable = True
