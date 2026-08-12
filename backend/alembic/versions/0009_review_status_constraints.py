"""Add the review-status CHECK constraints migration 0008 omitted.

The Document model declares ck_documents_translation_review_status and
ck_documents_document_review_status, but migration 0008 created the columns
without them. This migration adds both constraints, exactly matching the
model definitions, after a defensive cleanup of out-of-domain values.

Revision ID: 0009_review_status_constraints
Revises: 0008_prd_authorization_reviews
Create Date: 2026-08-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_review_status_constraints"
down_revision = "0008_prd_authorization_reviews"
branch_labels = None
depends_on = None

DOCUMENT_REVIEW_STATUSES = ("draft", "needs_review", "in_review", "approved", "rejected")


def upgrade() -> None:
    documents = sa.table(
        "documents",
        sa.column("translation_review_status", sa.String()),
        sa.column("document_review_status", sa.String()),
    )
    # Defensive cleanup so the constraints can apply to pre-existing rows.
    op.execute(
        documents.update()
        .where(
            documents.c.translation_review_status.is_not(None),
            documents.c.translation_review_status.notin_(["approved", "rejected"]),
        )
        .values(translation_review_status=None)
    )
    # document_review_status is NOT NULL (server default 'draft'), so
    # out-of-domain values reset to the column default instead of NULL.
    op.execute(
        documents.update()
        .where(
            sa.or_(
                documents.c.document_review_status.is_(None),
                documents.c.document_review_status.notin_(list(DOCUMENT_REVIEW_STATUSES)),
            )
        )
        .values(document_review_status="draft")
    )

    with op.batch_alter_table("documents") as batch:
        batch.create_check_constraint(
            "ck_documents_translation_review_status",
            "translation_review_status IS NULL OR "
            "translation_review_status IN ('approved', 'rejected')",
        )
        batch.create_check_constraint(
            "ck_documents_document_review_status",
            "document_review_status IN "
            "('draft', 'needs_review', 'in_review', 'approved', 'rejected')",
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint(
            "ck_documents_document_review_status",
            type_="check",
        )
        batch.drop_constraint(
            "ck_documents_translation_review_status",
            type_="check",
        )
