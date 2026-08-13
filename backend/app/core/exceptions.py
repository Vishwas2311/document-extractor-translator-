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


class JobCancelledError(AppError):
    """Raised when a worker notices the document was cancelled by the client."""

    code = "job_cancelled"
    status_code = 409
    retryable = False


class JobSupersededError(AppError):
    """Raised when a newer processing job replaced this worker's job."""

    code = "job_superseded"
    status_code = 409
    retryable = False


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


class AuthenticationError(AppError):
    code = "authentication_required"
    status_code = 401


class AuthorizationError(AppError):
    code = "authorization_denied"
    status_code = 403


class PolicyBlockedError(AppError):
    """Fail-closed security gateway denial before any external content transmission."""

    code = "processing_profile_blocked"
    status_code = 422


class RateLimitError(AppError):
    code = "rate_limit_exceeded"
    status_code = 429
    retryable = True


class ProviderQuotaError(AppError):
    """Fail-closed denial when a global provider budget or kill switch trips.

    A within-window retry cannot succeed, so this is deliberately non-retryable:
    it protects against runaway external cost and enables an operator stop switch.
    """

    code = "provider_quota_exceeded"
    status_code = 503
    retryable = False
