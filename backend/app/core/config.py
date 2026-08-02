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

    database_url: str | None = None
    storage_root: Path = Path("storage/documents")
    max_upload_size_mb: int = Field(default=50, ge=1, le=500)
    max_document_pages: int = Field(default=200, ge=1, le=2000)
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

    azure_openai_base_url: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_reasoning_effort: str = "minimal"
    azure_openai_max_completion_tokens: int = 8000

    target_language: str = "en"
    translation_max_blocks: int = 25
    translation_max_input_chars: int = 12000
    ocr_review_threshold: float = Field(default=0.85, ge=0, le=1)
    azure_max_retries: int = 3
    azure_request_timeout_seconds: int = 180
    processing_concurrency: int = 1
    job_lease_seconds: int = 300
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
        if self.auth_required and not self.api_auth_tokens.strip() and self.app_env == "development":
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
