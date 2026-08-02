"""Create document processing tables.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-31
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_extension", sa.String(12), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(32), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("source_languages", sa.JSON(), nullable=False),
        sa.Column("target_language", sa.String(12), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("processing_version", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_processing_jobs_document_id", "processing_jobs", ["document_id"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])

    op.create_table(
        "translation_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("model_deployment", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("input_block_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("artifact_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_translation_batches_document_id", "translation_batches", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_translation_batches_document_id", table_name="translation_batches")
    op.drop_table("translation_batches")
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_document_id", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_table("documents")
