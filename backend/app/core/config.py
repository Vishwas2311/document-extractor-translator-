import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[3])).resolve()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / "backend" / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CareTranslate Studio"
    app_env: str = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    frontend_origins: str = "http://localhost:3000,http://localhost:5173"

    # Auth: required by default. Set AUTH_REQUIRED=false only for ephemeral local demos.
    auth_required: bool = True
    api_auth_tokens: str = ""
    # Optional JSON map: {"token": {"subject":"...","organization_id":"...","roles":["reviewer"]}}
    api_auth_principals: str = ""

    database_url: str | None = None
    storage_root: Path = Path("storage/documents")
    # Scanned 300-page PDFs routinely exceed 50 MB.
    max_upload_size_mb: int = Field(default=150, ge=1, le=500)
    max_document_pages: int = Field(default=300, ge=1, le=2000)
    # Azure DI page-range size for large PDFs (Microsoft guidance: batch ~25–100 pages).
    di_page_range_size: int = Field(default=50, ge=1, le=200)
    # Bounded parallel DI range calls within one document (trusted totals / selective only).
    di_range_concurrency: int = Field(default=2, ge=1, le=8)
    # Prefer physically smaller PDF chunks over re-uploading the full source each range.
    di_use_physical_chunks: bool = True
    # When selected financial pages exceed this density, extract the full document once.
    di_dense_page_threshold: float = Field(default=0.65, ge=0.1, le=1.0)
    allowed_extensions: str = "pdf,png,jpg,jpeg,tif,tiff,bmp"
    rate_limit_per_minute: int = Field(default=120, ge=0, le=10000)
    use_create_all: bool = True

    # Data security gateway
    default_processing_profile: str = "GENAI_PSEUDONYMIZED"
    default_data_class: str = "synthetic"
    allow_synthetic_raw_llm: bool = True
    genai_raw_exception_enabled: bool = False
    pseudonymization_secret: str | None = None

    azure_auth_mode: str = "api_key"
    azure_document_intelligence_endpoint: str | None = None
    azure_document_intelligence_api_key: str | None = None
    azure_document_intelligence_model_id: str = "prebuilt-layout"
    azure_document_intelligence_features: str = "languages"

    # Financial extraction. Production selective mode requires an approved custom
    # classifier ID. The local evaluation default preserves full-layout analysis
    # while producing the same versioned financial contracts and UI artifacts.
    financial_extraction_mode: str = "post_extract"
    financial_classifier_model_id: str | None = None
    financial_classifier_version: str = "1.0"
    financial_classifier_split_mode: str = "perPage"
    financial_classifier_labels: str = (
        "balance_sheet,income_statement,cash_flow_statement,statement_of_changes,"
        "financial_summary,financial_table,invoice,bank_statement,payroll,tax,"
        "financial_notes,table_continuation"
    )
    financial_include_confidence: float = Field(default=0.65, ge=0, le=1)
    financial_exclude_confidence: float = Field(default=0.9, ge=0, le=1)
    financial_adjacent_pages: int = Field(default=1, ge=0, le=5)

    azure_openai_base_url: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_reasoning_effort: str = "minimal"
    # Raised for larger translation batches (40 blocks / 16k chars).
    azure_openai_max_completion_tokens: int = 12000

    target_language: str = "en"
    # Larger batches cut Azure OpenAI round-trips on dense multi-page docs.
    translation_max_blocks: int = 40
    translation_max_input_chars: int = 16000
    # In-document parallel AOAI batch calls (dominant speed lever for large PDFs).
    translation_concurrency: int = Field(default=8, ge=1, le=32)
    # Collapse identical source strings into one AOAI call, then fan out results.
    translation_dedupe_identical: bool = True
    # Flush progressive page writes every N completed translation batches (1 = every batch).
    translation_progress_flush_every: int = Field(default=4, ge=1, le=64)
    ocr_review_threshold: float = Field(default=0.85, ge=0, le=1)
    azure_max_retries: int = 3
    azure_request_timeout_seconds: int = 180
    processing_concurrency: int = 2
    # Long 300-page jobs need a longer lease than the historical 5-minute default.
    job_lease_seconds: int = 900
    job_heartbeat_seconds: int = 30
    recovery_sweep_seconds: int = 60

    log_level: str = "INFO"
    log_format: str = "json"

    @model_validator(mode="after")
    def resolve_local_paths(self) -> "Settings":
        if not self.storage_root.is_absolute():
            self.storage_root = (PROJECT_ROOT / self.storage_root).resolve()
        if not self.database_url:
            database_path = (PROJECT_ROOT / "data" / "application.db").resolve()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            self.database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
        if (
            self.auth_required
            and not self.api_auth_tokens.strip()
            and self.app_env == "development"
        ):
            # Deterministic local default so the app boots out of the box; override in .env.
            self.api_auth_tokens = "local-dev-token-change-me"
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origins.split(",") if item.strip()]

    @property
    def extension_set(self) -> set[str]:
        return {item.strip().lower().lstrip(".") for item in self.allowed_extensions.split(",")}

    @property
    def auth_token_set(self) -> set[str]:
        return {item.strip() for item in self.api_auth_tokens.split(",") if item.strip()}

    @property
    def auth_principal_map(self) -> dict[str, dict[str, object]]:
        from app.core.auth import parse_auth_principals

        try:
            return parse_auth_principals(self.api_auth_principals)
        except Exception as exc:  # noqa: BLE001 - fail closed at settings load
            raise ValueError(f"API_AUTH_PRINCIPALS is invalid: {exc}") from exc

    @property
    def document_intelligence_configured(self) -> bool:
        if self.azure_auth_mode == "managed_identity":
            return bool(self.azure_document_intelligence_endpoint)
        return bool(
            self.azure_document_intelligence_endpoint and self.azure_document_intelligence_api_key
        )

    @property
    def azure_openai_configured(self) -> bool:
        if self.azure_auth_mode == "managed_identity":
            return bool(self.azure_openai_base_url and self.azure_openai_deployment)
        return bool(
            self.azure_openai_base_url
            and self.azure_openai_api_key
            and self.azure_openai_deployment
        )

    @property
    def docs_enabled(self) -> bool:
        return self.app_env == "development" and self.debug

    @property
    def financial_label_set(self) -> set[str]:
        return {
            item.strip().casefold()
            for item in self.financial_classifier_labels.split(",")
            if item.strip()
        }

    @model_validator(mode="after")
    def validate_financial_extraction(self) -> "Settings":
        allowed_modes = {"off", "post_extract", "selective"}
        if self.financial_extraction_mode not in allowed_modes:
            raise ValueError(
                "FINANCIAL_EXTRACTION_MODE must be off, post_extract, or selective."
            )
        if (
            self.financial_extraction_mode == "selective"
            and not self.financial_classifier_model_id
        ):
            raise ValueError(
                "FINANCIAL_CLASSIFIER_MODEL_ID is required when selective financial "
                "extraction is enabled."
            )
        if self.financial_include_confidence > self.financial_exclude_confidence:
            raise ValueError(
                "FINANCIAL_INCLUDE_CONFIDENCE cannot exceed "
                "FINANCIAL_EXCLUDE_CONFIDENCE."
            )
        if self.financial_classifier_split_mode not in {"perPage", "auto", "none"}:
            raise ValueError(
                "FINANCIAL_CLASSIFIER_SPLIT_MODE must be perPage, auto, or none."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
