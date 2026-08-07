"""Add append-only financial reviewer decisions.

Revision ID: 0006_financial_reviews
Revises: 0005_financial_extraction
Create Date: 2026-08-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_financial_reviews"
down_revision = "0005_financial_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("financial_result_sha256", sa.String(64), nullable=True))
        batch.add_column(sa.Column("financial_review_status", sa.String(16), nullable=True))
        batch.add_column(sa.Column("financial_reviewed_by", sa.String(255), nullable=True))
        batch.add_column(sa.Column("financial_reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint(
            "ck_documents_financial_review_status",
            "financial_review_status IS NULL OR "
            "financial_review_status IN ('approved', 'rejected')",
        )

    op.create_table(
        "financial_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer_subject", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("corrections", sa.JSON(), nullable=False),
        sa.Column("processing_version", sa.String(64), nullable=False),
        sa.Column("result_schema_version", sa.String(64), nullable=False),
        sa.Column("result_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_financial_reviews_decision",
        ),
        sa.CheckConstraint(
            "length(result_sha256) = 64",
            name="ck_financial_reviews_result_sha256_length",
        ),
    )
    op.create_index("ix_financial_reviews_document_id", "financial_reviews", ["document_id"])
    op.create_index("ix_financial_reviews_decision", "financial_reviews", ["decision"])
    op.create_index("ix_financial_reviews_result_sha256", "financial_reviews", ["result_sha256"])


def downgrade() -> None:
    op.drop_index("ix_financial_reviews_result_sha256", table_name="financial_reviews")
    op.drop_index("ix_financial_reviews_decision", table_name="financial_reviews")
    op.drop_index("ix_financial_reviews_document_id", table_name="financial_reviews")
    op.drop_table("financial_reviews")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint(
            "ck_documents_financial_review_status",
            type_="check",
        )
        batch.drop_column("financial_reviewed_at")
        batch.drop_column("financial_reviewed_by")
        batch.drop_column("financial_review_status")
        batch.drop_column("financial_result_sha256")
