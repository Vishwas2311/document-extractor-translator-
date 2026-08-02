"""Drop the unused translation_batches table.

The application never wrote to this table - ProcessingService persists translation
batch results as flat JSON artifacts under storage instead. An empty, never-written
table left in place is a landmine for future reporting/auditing work built against it
returning no data, so it is removed here rather than left to accumulate schema drift.

Revision ID: 0002_drop_translation_batches
Revises: 0001_initial
Create Date: 2026-08-02
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_drop_translation_batches"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_translation_batches_document_id", table_name="translation_batches")
    op.drop_table("translation_batches")


def downgrade() -> None:
    op.create_table(
        "translation_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
